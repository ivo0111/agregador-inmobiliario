"""
services/normalizer.py
-----------------------
Funciones auxiliares para estandarizar cadenas de texto de ubicación,
extraer números limpios de m² y precios, y calcular similitud entre
campos de texto. Usado por el motor de deduplicación (Fase 3).

Diferencia con scrapers/utils/normalizador.py:
- Es genérico (no depende de selectores de Mercado Libre).
- Está pensado para el matching engine, no para el scraping.
- Incluye funciones de similitud textual necesarias para comparar
  barrios, departamentos y direcciones entre publicaciones.
"""

import re
import unicodedata
from typing import Optional


def normalizar_texto(texto: str) -> str:
    """
    Normaliza un string para comparaciones:
    - lowercase
    - elimina acentos
    - collapse de whitespace
    - elimina caracteres especiales (guiones, puntos, comas sueltas)
    """
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto.lower())
    texto = "".join(c for c in texto if unicodedata.category(c) != "Mn")
    texto = re.sub(r"[^a-z0-9\s]", " ", texto)
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto


def normalizar_ubicacion(texto: str) -> dict:
    """
    Recibe texto libre de ubicación y devuelve un dict con
    departamento, barrio y direccion normalizados.

    Usa DEPARTAMENTOS_MENDOZA como ancla para identificar el
    departamento, y el segmento anterior como barrio.
    """
    from schema import DEPARTAMENTOS_MENDOZA

    texto = (texto or "").strip()
    resultado = {"departamento": None, "barrio": None, "direccion": None}
    if not texto:
        return resultado

    segmentos = [s.strip() for s in texto.split(",") if s.strip()]
    if not segmentos:
        return resultado

    resultado["direccion"] = segmentos[0]

    departamentos_lower = {normalizar_texto(d): d for d in DEPARTAMENTOS_MENDOZA}

    segmentos_a_buscar = segmentos.copy()
    ultimo_es_provincia = (
        segmentos_a_buscar
        and normalizar_texto(segmentos_a_buscar[-1]) == "mendoza"
    )
    if ultimo_es_provincia and len(segmentos_a_buscar) > 1:
        segmentos_a_buscar = segmentos_a_buscar[:-1]

    encontrado = False
    for i in range(len(segmentos_a_buscar) - 1, -1, -1):
        clave = normalizar_texto(segmentos_a_buscar[i])
        if clave in departamentos_lower:
            resultado["departamento"] = departamentos_lower[clave]
            encontrado = True
            if i - 1 > 0:
                candidato_barrio = segmentos[i - 1]
                barrio_normalizado = normalizar_texto(candidato_barrio)
                if (
                    barrio_normalizado != "mendoza"
                    and barrio_normalizado != "provincia de mendoza"
                    and barrio_normalizado != "argentina"
                    and barrio_normalizado not in departamentos_lower
                ):
                    resultado["barrio"] = candidato_barrio
            break

    if not encontrado and ultimo_es_provincia:
        resultado["departamento"] = "Capital"

    return resultado


def extraer_m2(texto: str) -> Optional[float]:
    """
    Extrae la primera cantidad de metros cuadrados encontrada en un
    texto libre. Maneja formatos como:
        "70 m²", "70 m2", "70 mts cuadrados", "70 metros cuadrados"
        "70,5 m²", "1.500 m²"
    Devuelve None si no encuentra nada válida.
    """
    if not texto:
        return None

    texto = str(texto)
    texto_lower = texto.lower()

    patrones = [
        r"([\d.,]+)\s*m[²2]\s*(?:cubiertos|totales|cubierta|total)?",
        r"([\d.,]+)\s*mts?\s*(?:cuadrados|cúbicos)?",
        r"([\d.,]+)\s*metros\s*cuadrados",
    ]

    for patron in patrones:
        match = re.search(patron, texto_lower)
        if match:
            valor = _limpiar_numero(match.group(1))
            if valor is not None and valor > 0:
                return valor

    return None


def extraer_precio_limpio(texto: str) -> Optional[float]:
    """
    Extrae el precio numérico limpio de un texto. Detecta moneda
    (USD/ARS) y maneja formatos como:
        "US$130.000", "$48.500", "130.000 dólares", "48500"
    Devuelve None si no encuentra nada válida.
    """
    if not texto:
        return None

    texto = str(texto).strip()

    moneda = None
    if re.search(r"US\$|USD", texto, re.IGNORECASE):
        moneda = "USD"
    elif "$" in texto:
        moneda = "ARS"

    match_precio = re.search(r"(?:US\$|USD|\$)\s*([\d.,]+)", texto, re.IGNORECASE)
    if not match_precio:
        match_precio = re.search(r"([\d.,]+)\s*(?:dólares|dolares|usd|ars)?", texto, re.IGNORECASE)

    if match_precio:
        valor = _limpiar_numero(match_precio.group(1))
        if valor is not None and valor >= 0:
            return valor

    return None


def extraer_moneda(texto: str) -> Optional[str]:
    """Detecta la moneda en un texto: 'USD' o 'ARS'."""
    if not texto:
        return None
    texto = str(texto)
    if re.search(r"US\$|USD", texto, re.IGNORECASE):
        return "USD"
    if "$" in texto or re.search(r"ars|moneda local", texto, re.IGNORECASE):
        return "ARS"
    if re.search(r"dolares|d\u00f3lares", texto, re.IGNORECASE):
        return "USD"
    return None


def similitud_textos(a: str, b: str) -> float:
    """
    Similaridad Jaccard entre dos textos, basada en tokens normalizados.
    Retorna un float entre 0.0 y 1.0.
    Si ambos son vacios o None, se consideran identicos (1.0).
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    tokens_a = set(normalizar_texto(a).split())
    tokens_b = set(normalizar_texto(b).split())

    if not tokens_a and not tokens_b:
        return 1.0

    interseccion = tokens_a & tokens_b
    union = tokens_a | tokens_b

    return len(interseccion) / len(union) if union else 0.0


def similitud_ubicacion(loc1: dict, loc2: dict) -> float:
    """
    Score de similitud de ubicación entre dos dicts normalizados
    (como los devuelve normalizar_ubicacion).

    - Mismo departamento: +0.5
    - Mismo barrio (o similitud de tokens > 0.6): +0.5
    - Si alguno es None, se pondera proporcionalmente
    """
    score = 0.0
    peso_total = 0.0

    dep1 = loc1.get("departamento")
    dep2 = loc2.get("departamento")
    if dep1 and dep2:
        peso_total += 0.5
        if normalizar_texto(dep1) == normalizar_texto(dep2):
            score += 0.5
    elif dep1 or dep2:
        peso_total += 0.25

    bar1 = loc1.get("barrio")
    bar2 = loc2.get("barrio")
    if bar1 and bar2:
        peso_total += 0.5
        norm1 = normalizar_texto(bar1)
        norm2 = normalizar_texto(bar2)
        if norm1 == norm2:
            score += 0.5
        else:
            score += 0.5 * similitud_textos(bar1, bar2)
    elif bar1 or bar2:
        peso_total += 0.25
        if bar1 and bar2:
            score += 0.25 * similitud_textos(bar1, bar2)

    if peso_total == 0:
        return 0.0

    return score / peso_total


def _limpiar_numero(texto) -> Optional[float]:
    """Convierte strings como '1.500' o '1.500,50' o 250 a float."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)

    texto = str(texto).strip()
    if not texto:
        return None

    texto = texto.replace(".", "").replace(",", ".")
    match = re.search(r"-?\d+(\.\d+)?", texto)
    return float(match.group()) if match else None