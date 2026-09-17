"""
services/deduplicator.py
-------------------------
Motor de agrupamiento y deduplicación (Fase 3).

Procesa las publicaciones existentes en la base de datos que
aún no tienen inmueble_id asignado, determina si corresponden
a un mismo inmueble físico y crea o actualiza los registros
de la tabla inmuebles enlazando las publicaciones.

Es la ÚNICA capa que crea inmuebles nuevos (db/repository.py ya no
lo hace al insertar publicaciones — ver su docstring). Procesa las
publicaciones en orden de fecha_extraccion, y cada inmueble que crea
queda disponible en memoria para las publicaciones siguientes de la
misma corrida, así que dos publicaciones nuevas del mismo batch
(distintos portales, mismo inmueble físico) sí pueden agruparse entre
sí sin necesitar una segunda corrida.

Criterios de coincidencia (todos deben cumplirse):
  1. Similitud alta en ubicación (departamento + barrio).
  2. Dormitorios y baños idénticos (si ambos tienen valor).
  3. Superficie m² con diferencia ≤ 3%.
  4. Precio en la misma moneda con diferencia ≤ 5%.

Todo el proceso se ejecuta dentro de una transacción segura
usando psycopg v3.
"""

from dataclasses import dataclass, field
from typing import Optional

import psycopg

from config import get_logger
from services.normalizer import (
    extraer_m2,
    extraer_precio_limpio,
    normalizar_ubicacion,
    similitud_ubicacion,
)

logger = get_logger("services.deduplicator")

# Umbrales del algoritmo de matching
SIMILARIDAD_UBICACION_MIN = 0.7
DIFERENCIA_SUPERFICIE_MAX = 0.03
DIFERENCIA_PRECIO_MAX = 0.05


@dataclass
class ResultadoDedup:
    publicaciones_asignadas: int = 0
    publicaciones_ya_asignadas: int = 0
    inmuebles_creados: int = 0
    inmuebles_reutilizados: int = 0
    errores: int = 0


class DeduplicatorEngine:
    """
    Motor de deduplicación. Recibe una conexión psycopg y
    ejecuta el proceso completo de matching y asignación.

    Uso:
        with obtener_conexion() as conn:
            engine = DeduplicatorEngine(conn)
            resultado = engine.ejecutar()
    """

    def __init__(self, conn: psycopg.Connection):
        self._conn = conn

    def ejecutar(self) -> ResultadoDedup:
        """
        Punto de entrada principal. Ejecuta el proceso completo
        de deduplicación dentro de una transacción.

        Flujo:
          1. Obtener publicaciones sin inmueble_id.
          2. Obtener inmuebles existentes.
          3. Para cada publicación sin inmueble (en orden de
             fecha_extraccion):
             a. Intentar match contra inmuebles existentes (incluye
                los creados más temprano en esta misma corrida).
             b. Si match encontrado → asignar inmueble_id.
             c. Si no match → crear nuevo inmueble y agregarlo a la
                lista en memoria para que publicaciones siguientes
                puedan matchear contra él.
          4. Commit de la transacción.
        """
        resultado = ResultadoDedup()

        publicaciones_sin_inmueble = self._obtener_publicaciones_sin_inmueble()
        if not publicaciones_sin_inmueble:
            logger.info("No hay publicaciones sin asignar. Deduplicación omitida.")
            return resultado

        inmuebles_existentes = self._obtener_inmuebles_existentes()
        logger.info(
            "Procesando %d publicaciones sin inmueble contra %d inmuebles existentes",
            len(publicaciones_sin_inmueble),
            len(inmuebles_existentes),
        )

        for pub in publicaciones_sin_inmueble:
            try:
                inmueble_id = self._buscar_match(pub, inmuebles_existentes)
                if inmueble_id is not None:
                    self._asignar_inmueble(pub["id"], inmueble_id)
                    resultado.publicaciones_asignadas += 1
                    resultado.inmuebles_reutilizados += 1
                else:
                    inmueble_id = self._crear_inmueble_desde_publicacion(pub)
                    self._asignar_inmueble(pub["id"], inmueble_id)
                    resultado.publicaciones_asignadas += 1
                    resultado.inmuebles_creados += 1

                    # FIX clave: agregamos el inmueble recién creado a la
                    # lista en memoria. Si no hiciéramos esto, dos
                    # publicaciones NUEVAS del mismo batch (ej. el mismo
                    # depto scrapeado de ML y de otro portal en la misma
                    # corrida, ninguna todavía en la tabla `inmuebles`)
                    # jamás se agruparían entre sí: la publicación #2
                    # solo vería la foto de `inmuebles` tomada ANTES de
                    # que la publicación #1 creara su inmueble.
                    inmuebles_existentes.append(
                        self._inmueble_dict_desde_pub(inmueble_id, pub)
                    )
            except Exception as exc:
                logger.error(
                    "Error deduplicando publicación id=%s: %s",
                    pub.get("id"), exc,
                )
                resultado.errores += 1

        self._conn.commit()
        logger.info(
            "Deduplicación completada: %d asignadas, %d inmuebles creados, %d errores",
            resultado.publicaciones_asignadas,
            resultado.inmuebles_creados,
            resultado.errores,
        )
        return resultado

    # ------------------------------------------------------------------ #
    # Consultas a base de datos
    # ------------------------------------------------------------------ #

    def _obtener_publicaciones_sin_inmueble(self) -> list[dict]:
        """Devuelve todas las publicaciones cuyo inmueble_id es NULL."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, fuente, id_fuente, url, titulo, tipo_operacion,
                       precio, moneda, provincia, departamento, barrio,
                       direccion, latitud, longitud,
                       superficie_cubierta_m2, superficie_total_m2,
                       ambientes, dormitorios, banios, cochera,
                       fecha_extraccion
                FROM publicaciones
                WHERE inmueble_id IS NULL
                ORDER BY fecha_extraccion ASC
                """
            )
            columnas = [desc[0] for desc in cur.description]
            return [dict(zip(columnas, fila)) for fila in cur.fetchall()]

    def _obtener_inmuebles_existentes(self) -> list[dict]:
        """Devuelve todos los inmuebles canónicos ya creados."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, titulo_representativo, tipo_propiedad, provincia,
                       departamento, barrio, direccion, latitud, longitud,
                       superficie_cubierta_m2, superficie_total_m2,
                       ambientes, dormitorios, banios, cochera,
                       hash_deduplicacion
                FROM inmuebles
                ORDER BY id ASC
                """
            )
            columnas = [desc[0] for desc in cur.description]
            return [dict(zip(columnas, fila)) for fila in cur.fetchall()]

    # ------------------------------------------------------------------ #
    # Lógica de matching
    # ------------------------------------------------------------------ #

    def _buscar_match(self, pub: dict, inmuebles: list[dict]) -> Optional[int]:
        """
        Busca, entre los inmuebles existentes (incluyendo los creados
        más temprano en esta misma corrida — ver `ejecutar()`), uno
        que coincida con la publicación según los 4 criterios.
        """
        pub_loc = normalizar_ubicacion(
            self._armar_texto_ubicacion(pub)
        )
        pub_m2 = pub.get("superficie_cubierta_m2") or pub.get("superficie_total_m2")
        pub_precio = pub.get("precio")
        pub_moneda = pub.get("moneda")
        pub_dormitorios = pub.get("dormitorios")
        pub_banios = pub.get("banios")

        for inmueble in inmuebles:
            if self._criterios_coinciden(
                pub_loc, pub_m2, pub_precio, pub_moneda,
                pub_dormitorios, pub_banios,
                inmueble,
            ):
                return inmueble["id"]

        return None

    def _criterios_coinciden(
        self,
        pub_loc: dict,
        pub_m2: Optional[float],
        pub_precio: Optional[float],
        pub_moneda: Optional[str],
        pub_dormitorios: Optional[int],
        pub_banios: Optional[int],
        inmueble: dict,
    ) -> bool:
        """
        Evalúa si una publicación coincide con un inmueble
        según los 4 criterios definidos. Todos deben pasar.
        """
        # Criterio 1: Similitud de ubicación
        inmueble_loc = {
            "departamento": inmueble.get("departamento"),
            "barrio": inmueble.get("barrio"),
            "direccion": inmueble.get("direccion"),
        }
        sim_loc = similitud_ubicacion(pub_loc, inmueble_loc)
        if sim_loc < SIMILARIDAD_UBICACION_MIN:
            return False

        # Criterio 2: Dormitorios y baños idénticos (si ambos tienen valor)
        inmueble_dorm = inmueble.get("dormitorios")
        inmueble_banios = inmueble.get("banios")

        if pub_dormitorios is not None and inmueble_dorm is not None:
            if pub_dormitorios != inmueble_dorm:
                return False

        if pub_banios is not None and inmueble_banios is not None:
            if pub_banios != inmueble_banios:
                return False

        # Criterio 3: Superficie m² con diferencia ≤ 3%
        inmueble_m2 = (
            inmueble.get("superficie_cubierta_m2")
            or inmueble.get("superficie_total_m2")
        )
        if pub_m2 is not None and inmueble_m2 is not None:
            if inmueble_m2 == 0:
                return False
            diferencia = abs(pub_m2 - inmueble_m2) / inmueble_m2
            if diferencia > DIFERENCIA_SUPERFICIE_MAX:
                return False

        # Criterio 4: Precio en la misma moneda con diferencia ≤ 5%
        inmueble_precio, inmueble_moneda = self._obtener_precio_inmueble(inmueble)
        if pub_precio is not None and inmueble_precio is not None:
            if pub_moneda is not None and inmueble_moneda is not None:
                if pub_moneda != inmueble_moneda:
                    return False
            if inmueble_precio == 0:
                return False
            diferencia_precio = abs(pub_precio - inmueble_precio) / inmueble_precio
            if diferencia_precio > DIFERENCIA_PRECIO_MAX:
                return False

        return True

    def _obtener_precio_inmueble(self, inmueble: dict) -> tuple[Optional[float], Optional[str]]:
        """
        Obtiene el precio y la moneda de un inmueble consultando
        la primera publicación vinculada. Los inmuebles no tienen
        precio directo; el precio y la moneda viven en la publicación.
        """
        inmueble_id = inmueble.get("id")
        if inmueble_id is None:
            return None, None
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT precio, moneda FROM publicaciones WHERE inmueble_id = %s LIMIT 1",
                (inmueble_id,),
            )
            fila = cur.fetchone()
            if fila is None:
                return None, None
            return fila[0], fila[1]

    # ------------------------------------------------------------------ #
    # Creación y asignación
    # ------------------------------------------------------------------ #

    def _crear_inmueble_desde_publicacion(self, pub: dict) -> int:
        """
        Crea un nuevo registro en inmuebles a partir de los datos
        de una publicación, generando valores canónicos.
        """
        ubicacion = normalizar_ubicacion(
            self._armar_texto_ubicacion(pub)
        )
        titulo = self._generar_titulo_canonico(pub, ubicacion)

        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO inmuebles (
                    titulo_representativo, tipo_propiedad, provincia,
                    departamento, barrio, direccion,
                    latitud, longitud,
                    superficie_cubierta_m2, superficie_total_m2,
                    ambientes, dormitorios, banios, cochera,
                    hash_deduplicacion
                ) VALUES (
                    %(titulo)s, %(tipo_propiedad)s, %(provincia)s,
                    %(departamento)s, %(barrio)s, %(direccion)s,
                    %(latitud)s, %(longitud)s,
                    %(superficie_cubierta_m2)s, %(superficie_total_m2)s,
                    %(ambientes)s, %(dormitorios)s, %(banios)s, %(cochera)s,
                    %(hash_deduplicado)s
                )
                RETURNING id
                """,
                {
                    "titulo": titulo,
                    "tipo_propiedad": pub.get("tipo_propiedad"),
                    "provincia": pub.get("provincia", "Mendoza"),
                    "departamento": ubicacion.get("departamento"),
                    "barrio": ubicacion.get("barrio"),
                    "direccion": ubicacion.get("direccion") or pub.get("direccion"),
                    "latitud": pub.get("latitud"),
                    "longitud": pub.get("longitud"),
                    "superficie_cubierta_m2": pub.get("superficie_cubierta_m2"),
                    "superficie_total_m2": pub.get("superficie_total_m2"),
                    "ambientes": pub.get("ambientes"),
                    "dormitorios": pub.get("dormitorios"),
                    "banios": pub.get("banios"),
                    "cochera": pub.get("cochera"),
                    "hash_deduplicado": pub.get("hash_duplicado"),
                },
            )
            inmueble_id = cur.fetchone()[0]

        logger.info("Inmueble creado: id=%d - %s", inmueble_id, titulo)
        return inmueble_id

    def _inmueble_dict_desde_pub(self, inmueble_id: int, pub: dict) -> dict:
        """
        Arma un dict con la misma forma que devuelve
        `_obtener_inmuebles_existentes()`, a partir de una publicación
        recién convertida en inmueble. Se usa para actualizar la lista
        de inmuebles en memoria dentro de `ejecutar()` sin tener que
        volver a golpear la base de datos (ver comentario en `ejecutar`).
        """
        ubicacion = normalizar_ubicacion(
            self._armar_texto_ubicacion(pub)
        )
        return {
            "id": inmueble_id,
            "titulo_representativo": None,
            "tipo_propiedad": pub.get("tipo_propiedad"),
            "provincia": pub.get("provincia", "Mendoza"),
            "departamento": ubicacion.get("departamento"),
            "barrio": ubicacion.get("barrio"),
            "direccion": ubicacion.get("direccion") or pub.get("direccion"),
            "latitud": pub.get("latitud"),
            "longitud": pub.get("longitud"),
            "superficie_cubierta_m2": pub.get("superficie_cubierta_m2"),
            "superficie_total_m2": pub.get("superficie_total_m2"),
            "ambientes": pub.get("ambientes"),
            "dormitorios": pub.get("dormitorios"),
            "banios": pub.get("banios"),
            "cochera": pub.get("cochera"),
            "hash_deduplicacion": pub.get("hash_duplicado"),
        }

    def _generar_titulo_canonico(self, pub: dict, ubicacion: dict) -> str:
        """
        Genera un título canónico para el inmueble combinando
        tipo de propiedad, departamento, barrio y superficie.
        """
        partes = []

        tipo = pub.get("tipo_propiedad")
        if tipo:
            partes.append(tipo.capitalize())

        dep = ubicacion.get("departamento")
        if dep:
            partes.append(dep)

        barrio = ubicacion.get("barrio")
        if barrio:
            partes.append(barrio)

        m2 = pub.get("superficie_cubierta_m2") or pub.get("superficie_total_m2")
        if m2:
            partes.append(f"{m2:.0f} m²")

        if not partes:
            return pub.get("titulo") or "Inmueble"

        return " - ".join(partes)

    def _asignar_inmueble(self, publicacion_id: int, inmueble_id: int) -> None:
        """Asigna un inmueble_id a una publicación."""
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE publicaciones SET inmueble_id = %s WHERE id = %s",
                (inmueble_id, publicacion_id),
            )

    # ------------------------------------------------------------------ #
    # Utilidades
    # ------------------------------------------------------------------ #

    def _armar_texto_ubicacion(self, pub: dict) -> str:
        """
        Concatena los campos de ubicación de una publicación en
        un solo texto para normalización.
        """
        partes = []
        for campo in ["direccion", "barrio", "departamento", "provincia"]:
            valor = pub.get(campo)
            if valor:
                partes.append(str(valor))
        return ", ".join(partes)