"""
db/repository.py
-----------------
Toda la lógica de persistencia vive acá, separada de los scrapers. Un
scraper no debería saber nada de SQL; solo entrega una lista de dicts
con forma schema.Propiedad, y esta capa se encarga de guardarlos.

Flujo por cada propiedad extraída:
  1. ¿Existe ya un inmueble con el mismo hash_deduplicacion? (matching
     barato entre fuentes)
     - Sí -> reutilizamos ese inmueble_id.
     - No -> creamos un inmueble nuevo con los datos "canónicos".
  2. UPSERT de la publicación (UNIQUE(fuente, id_fuente)):
     - Si no existía -> INSERT.
     - Si ya existía -> UPDATE de precio/fotos/fecha_extraccion/etc.
       vía ON CONFLICT DO UPDATE (no se duplica la fila).
"""

from dataclasses import dataclass
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from config import get_logger

logger = get_logger("db.repository")

SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


@dataclass
class ResultadoGuardado:
    """Estadísticas de una corrida de guardado, para loggear/reportar."""
    publicaciones_nuevas: int = 0
    publicaciones_actualizadas: int = 0
    inmuebles_creados: int = 0
    inmuebles_reutilizados: int = 0
    errores: int = 0


def crear_esquema(conn: psycopg.Connection) -> None:
    """Ejecuta schema.sql. Es idempotente (todo CREATE usa IF NOT EXISTS)."""
    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info("Esquema aplicado correctamente.")


def _buscar_inmueble_por_hash(conn: psycopg.Connection, hash_dedup: str) -> int | None:
    if not hash_dedup:
        return None
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM inmuebles WHERE hash_deduplicacion = %s LIMIT 1",
            (hash_dedup,),
        )
        fila = cur.fetchone()
        return fila[0] if fila else None


def _crear_inmueble(conn: psycopg.Connection, propiedad: dict) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inmuebles (
                titulo_representativo, tipo_propiedad, provincia, departamento,
                barrio, direccion, latitud, longitud,
                superficie_cubierta_m2, superficie_total_m2,
                ambientes, dormitorios, banios, cochera, hash_deduplicacion
            ) VALUES (
                %(titulo)s, %(tipo_propiedad)s, %(provincia)s, %(departamento)s,
                %(barrio)s, %(direccion)s, %(latitud)s, %(longitud)s,
                %(superficie_cubierta_m2)s, %(superficie_total_m2)s,
                %(ambientes)s, %(dormitorios)s, %(banios)s, %(cochera)s, %(hash_duplicado)s
            )
            RETURNING id
            """,
            propiedad,
        )
        return cur.fetchone()[0]


def _buscar_publicacion_existente(conn: psycopg.Connection, fuente: str, id_fuente: str) -> int | None:
    """Devuelve el inmueble_id ya asignado a esta publicación, si ya existe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT inmueble_id FROM publicaciones WHERE fuente = %s AND id_fuente = %s",
            (fuente, id_fuente),
        )
        fila = cur.fetchone()
        return fila[0] if fila else None


def _obtener_o_crear_inmueble(conn: psycopg.Connection, propiedad: dict) -> tuple[int, bool]:
    """
    Devuelve (inmueble_id, fue_creado). fue_creado=False si se reutilizó
    uno existente (ya sea porque esta publicación ya estaba vinculada a
    un inmueble, o porque matcheó por hash con uno de otra fuente).

    IMPORTANTE: si la publicación YA EXISTE (se está re-scrapeando),
    reusamos directamente su inmueble_id ya asignado, SIN volver a
    correr el matching por hash. Si hiciéramos matching de nuevo acá,
    un cambio de precio (o cualquier campo que afecte el hash) podría
    hacer que la misma publicación "pierda" su vínculo original y cree
    un inmueble fantasma nuevo — es exactamente el bug que encontramos
    probando esto contra una base real.
    """
    inmueble_existente = _buscar_publicacion_existente(
        conn, propiedad["portal"], propiedad["id_fuente"]
    )
    if inmueble_existente is not None:
        return inmueble_existente, False

    hash_dedup = propiedad.get("hash_duplicado")
    inmueble_id = _buscar_inmueble_por_hash(conn, hash_dedup)
    if inmueble_id is not None:
        return inmueble_id, False

    inmueble_id = _crear_inmueble(conn, propiedad)
    return inmueble_id, True


def _upsert_publicacion(conn: psycopg.Connection, propiedad: dict, inmueble_id: int) -> bool:
    """
    Inserta o actualiza la publicación. Devuelve True si fue INSERT
    (publicación nueva), False si fue UPDATE (ya existía).

    El truco para distinguir INSERT de UPDATE con una sola query es
    comparar xmax: xmax = 0 en una fila recién insertada dentro de la
    misma transacción; distinto de 0 si la fila fue tocada por UPDATE.
    Es un patrón estándar de PostgreSQL para este caso.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO publicaciones (
                inmueble_id, fuente, id_fuente, url, titulo, tipo_operacion,
                precio, moneda, fotos, foto_portada, fecha_extraccion
            ) VALUES (
                %(inmueble_id)s, %(fuente)s, %(id_fuente)s, %(url)s, %(titulo)s,
                %(tipo_operacion)s, %(precio)s, %(moneda)s, %(fotos)s,
                %(foto_portada)s, %(fecha_extraccion)s
            )
            ON CONFLICT (fuente, id_fuente) DO UPDATE SET
                precio            = EXCLUDED.precio,
                moneda            = EXCLUDED.moneda,
                titulo            = EXCLUDED.titulo,
                fotos             = EXCLUDED.fotos,
                foto_portada      = EXCLUDED.foto_portada,
                fecha_extraccion  = EXCLUDED.fecha_extraccion,
                url               = EXCLUDED.url
            RETURNING (xmax = 0) AS fue_insert
            """,
            {
                "inmueble_id": inmueble_id,
                "fuente": propiedad["portal"],
                "id_fuente": propiedad["id_fuente"],
                "url": propiedad["url_fuente"],
                "titulo": propiedad["titulo"],
                "tipo_operacion": propiedad["tipo_operacion"],
                "precio": propiedad["precio"],
                "moneda": propiedad["moneda"],
                "fotos": Jsonb(propiedad.get("fotos") or []),
                "foto_portada": propiedad.get("foto_portada"),
                "fecha_extraccion": propiedad["fecha_extraccion"],
            },
        )
        return cur.fetchone()[0]


def guardar_propiedades(conn: psycopg.Connection, propiedades: list[dict]) -> ResultadoGuardado:
    """
    Punto de entrada principal de esta capa. Recibe la lista de dicts
    que devuelve cualquier scraper (schema.Propiedad.to_dict()) y las
    persiste, con deduplicación de inmuebles y upsert de publicaciones.

    Usa una transacción por propiedad (no una gigante para todo el
    batch) para que si una falla, no se pierda el trabajo de las demás.
    """
    resultado = ResultadoGuardado()

    for propiedad in propiedades:
        try:
            inmueble_id, fue_creado = _obtener_o_crear_inmueble(conn, propiedad)
            fue_insert = _upsert_publicacion(conn, propiedad, inmueble_id)
            conn.commit()

            if fue_creado:
                resultado.inmuebles_creados += 1
            else:
                resultado.inmuebles_reutilizados += 1

            if fue_insert:
                resultado.publicaciones_nuevas += 1
            else:
                resultado.publicaciones_actualizadas += 1

        except Exception as exc:
            conn.rollback()
            resultado.errores += 1
            logger.warning(
                "Error guardando publicación %s/%s: %s",
                propiedad.get("portal"), propiedad.get("id_fuente"), exc,
            )

    logger.info(
        "Guardado completo: %d publicaciones nuevas, %d actualizadas, "
        "%d inmuebles creados, %d reutilizados, %d errores.",
        resultado.publicaciones_nuevas, resultado.publicaciones_actualizadas,
        resultado.inmuebles_creados, resultado.inmuebles_reutilizados, resultado.errores,
    )
    return resultado
