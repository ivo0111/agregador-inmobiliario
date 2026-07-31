"""
normalizador.py
---------------
Funciones puras (sin efectos secundarios) para convertir datos "crudos"
de un portal en los tipos correctos de nuestro esquema (schema.Propiedad).

Mantener esta lógica separada del scraper hace que sea reutilizable
cuando agreguemos Zonaprop/Argenprop en próximas fases: cada portal solo
necesita extraer el texto crudo, y estas funciones lo limpian.
"""

import re
from typing import Optional


def limpiar_numero(texto) -> Optional[float]:
    """
    Convierte strings como '1.500' o '1.500,50' o 250 (ya numérico) a float.
    Devuelve None si no puede parsear.
    """
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)

    texto = str(texto).strip()
    if not texto:
        return None

    # Formato AR: punto = miles, coma = decimales
    texto = texto.replace(".", "").replace(",", ".")
    match = re.search(r"-?\d+(\.\d+)?", texto)
    return float(match.group()) if match else None


def extraer_atributos_desde_texto(texto: str) -> dict:
    """
    Las cards de resultados de Mercado Libre muestran los atributos como
    texto plano suelto, por ejemplo:
        "3 ambs. 2 baños · 70 m² cubiertos"
        "2 dormitorios · 1 baño · 65 m² cubiertos"
        "382 m² cubiertos · 1.014 m² totales"

    Esta función usa regex tolerantes para extraer lo que haya, sin
    asumir un orden fijo (porque ML no siempre muestra todos los campos
    ni en el mismo orden).
    """
    texto = texto or ""
    texto_lower = texto.lower()
    resultado = {
        "ambientes": None,
        "dormitorios": None,
        "banios": None,
        "superficie_cubierta_m2": None,
        "superficie_total_m2": None,
        "cochera": None,
    }

    match_ambientes = re.search(r"(\d+)\s*amb", texto_lower)
    if match_ambientes:
        resultado["ambientes"] = int(match_ambientes.group(1))

    match_dormitorios = re.search(r"(\d+)\s*dormitorios?", texto_lower)
    if match_dormitorios:
        resultado["dormitorios"] = int(match_dormitorios.group(1))

    match_banios = re.search(r"(\d+)\s*baños?", texto_lower)
    if match_banios:
        resultado["banios"] = int(match_banios.group(1))

    match_cubierta = re.search(r"([\d.,]+)\s*m[²2]\s*cubiertos?", texto_lower)
    if match_cubierta:
        resultado["superficie_cubierta_m2"] = limpiar_numero(match_cubierta.group(1))

    match_total = re.search(r"([\d.,]+)\s*m[²2]\s*totales?", texto_lower)
    if match_total:
        resultado["superficie_total_m2"] = limpiar_numero(match_total.group(1))

    # Si no hay distinción cubierta/total y solo aparece "m²" a secas,
    # lo tomamos como superficie cubierta (comportamiento más común).
    if resultado["superficie_cubierta_m2"] is None and resultado["superficie_total_m2"] is None:
        match_generico = re.search(r"([\d.,]+)\s*m[²2]", texto_lower)
        if match_generico:
            resultado["superficie_cubierta_m2"] = limpiar_numero(match_generico.group(1))

    if "cochera" in texto_lower or "garage" in texto_lower:
        resultado["cochera"] = True

    return resultado


def extraer_precio_moneda(texto: str) -> dict:
    """
    Convierte textos de precio como 'US$130.000' o '$48.500' en
    (precio: float, moneda: 'USD'|'ARS').
    """
    texto = (texto or "").strip()
    if re.search(r"US\$|USD", texto, re.IGNORECASE):
        moneda = "USD"
    elif "$" in texto:
        moneda = "ARS"
    else:
        moneda = None

    # Tomamos el número que sigue inmediatamente al símbolo de moneda,
    # no el primer número del texto completo (que podría ser otra cosa,
    # ej. "3 ambs." si el texto viene con contexto extra).
    match_precio = re.search(r"(?:US\$|USD|\$)\s*([\d.,]+)", texto, re.IGNORECASE)
    precio = limpiar_numero(match_precio.group(1)) if match_precio else None

    return {
        "precio": precio,
        "moneda": moneda,
    }


def extraer_ubicacion_desde_texto(texto: str) -> dict:
    """
    Las cards de ML muestran la ubicación como texto libre, por ejemplo:
        "Anatole France 739, Godoy Cruz, Provincia De Mendoza, Argentina, Godoy Cruz, Mendoza"
        "Coronel Rodriguez 67, Mendoza"

    No hay un formato único, así que usamos la lista de departamentos
    conocidos de Mendoza (schema.DEPARTAMENTOS_MENDOZA) como ancla: el
    segmento que coincide con un departamento conocido nos da
    'departamento', y el segmento inmediatamente anterior (si no es
    "Mendoza" ni "Provincia de Mendoza") suele ser el barrio.
    """
    from schema import DEPARTAMENTOS_MENDOZA  # import local para evitar ciclos

    texto = (texto or "").strip()
    resultado = {"departamento": None, "barrio": None, "direccion": None}
    if not texto:
        return resultado

    segmentos = [s.strip() for s in texto.split(",") if s.strip()]
    if not segmentos:
        return resultado

    resultado["direccion"] = segmentos[0]

    departamentos_lower = {d.lower(): d for d in DEPARTAMENTOS_MENDOZA}

    # OJO: ML suele repetir el nombre de la ciudad/departamento dos veces
    # en la misma dirección, y casi siempre termina la cadena con
    # "Mendoza" a secas (el nombre de la PROVINCIA, no un departamento).
    # Si buscáramos "mendoza" como si fuera el departamento "Capital"
    # sin más cuidado, ese sufijo final nos taparía el departamento real
    # (ej: "Godoy Cruz") que aparece un poco antes. Por eso:
    #   1. Buscamos desde el final, pero ignorando un último segmento
    #      que sea literalmente "Mendoza" (se trata como sufijo de
    #      provincia, no como departamento).
    #   2. Solo si NINGÚN otro departamento aparece en el texto,
    #      interpretamos ese "Mendoza" final como el departamento
    #      Capital (caso de direcciones dentro de la Ciudad de Mendoza).
    segmentos_a_buscar = segmentos.copy()
    ultimo_es_provincia = segmentos_a_buscar and segmentos_a_buscar[-1].lower() == "mendoza"
    if ultimo_es_provincia and len(segmentos_a_buscar) > 1:
        segmentos_a_buscar = segmentos_a_buscar[:-1]

    encontrado = False
    for i in range(len(segmentos_a_buscar) - 1, -1, -1):
        clave = segmentos_a_buscar[i].lower()
        if clave in departamentos_lower:
            resultado["departamento"] = departamentos_lower[clave]
            encontrado = True
            # i - 1 == 0 significa que el "candidato a barrio" es en
            # realidad el segmento 0 (la dirección/calle) — ahí no hay
            # barrio distinto informado, así que lo dejamos en None.
            if i - 1 > 0:
                candidato_barrio = segmentos[i - 1]
                if candidato_barrio.lower() not in ("mendoza", "provincia de mendoza", "argentina") \
                        and candidato_barrio.lower() not in departamentos_lower:
                    resultado["barrio"] = candidato_barrio
            break

    if not encontrado and ultimo_es_provincia:
        # No apareció ningún departamento explícito: asumimos que la
        # propiedad está en la Ciudad de Mendoza (Capital).
        resultado["departamento"] = "Capital"

    return resultado