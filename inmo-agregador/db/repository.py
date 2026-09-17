"""
db/repository.py
-----------------
Toda la lógica de persistencia vive acá, separada de los scrapers. Un
scraper no debería saber nada de SQL; solo entrega una lista de dicts
con forma schema.Propiedad, y esta capa se encarga de guardarlos.

Flujo por cada propiedad extraída:
  1. ¿Esta publicación (mismo fuente + id_fuente) ya existía? Si ya
     estaba vinculada a un inmueble (por una corrida anterior de
     DeduplicatorEngine), reutilizamos ese vínculo tal cual.
  2. Si es una publicación NUEVA, la guardamos con inmueble_id = NULL
     a propósito. NO se intenta matchear/crear un inmueble acá por
     hash: ese matching barato generaba un inmueble "provisorio" por
     cada publicación nueva y dejaba a DeduplicatorEngine sin nada
     para procesar (siempre encontraba 0 publicaciones con
     inmueble_id IS NULL). El agrupamiento fino por ubicación/m²/
     precio/ambientes es responsabilidad exclusiva de
     services.deduplicator.DeduplicatorEngine, que corre después.
  3. UPSERT de la publicación (UNIQUE(fuente, id_fuente)):
     - Si no existía -> INSERT.
     - Si ya existía -> UPDATE de precio/fotos/fecha_extraccion/etc.
       vía ON CONFLICT DO UPDATE (no se duplica la fila, y el
       inmueble_id que ya tuviera se preserva).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg
from psycopg.types.json import Jsonb

from config import get_logger

logger = get_logger("db.repository")

SCHEMA_SQL_PATH = Path(__file__).parent / "schema.sql"


@dataclass
class ResultadoGuardado:
    """
    Estadísticas de una corrida de guardado, para loggear/reportar.

    La creación/agrupamiento de inmuebles ya NO pasa por esta capa
    (ver DeduplicatorEngine), así que acá solo se reportan las
    publicaciones.
    """
    publicaciones_nuevas: int = 0
    publicaciones_actualizadas: int = 0
    errores: int = 0


def crear_esquema(conn: psycopg.Connection) -> None:
    """Ejecuta schema.sql. Es idempotente (todo CREATE usa IF NOT EXISTS)."""
    sql = SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
    logger.info("Esquema aplicado correctamente.")


def _buscar_publicacion_existente(conn: psycopg.Connection, fuente: str, id_fuente: str) -> Optional[int]:
    """
    Devuelve el inmueble_id ya asignado a esta publicación, si la
    publicación ya existía en la tabla (se está re-scrapeando).
    Puede devolver None tanto si la publicación es nueva como si ya
    existía pero todavía no fue procesada por DeduplicatorEngine.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT inmueble_id FROM publicaciones WHERE fuente = %s AND id_fuente = %s",
            (fuente, id_fuente),
        )
        fila = cur.fetchone()
        return fila[0] if fila else None


def _resolver_inmueble_id(conn: psycopg.Connection, propiedad: dict) -> Optional[int]:
    """
    Devuelve el inmueble_id a usar en el upsert de esta publicación.

    - Si la publicación ya existía (re-scrape), reutiliza el
      inmueble_id que ya tenía asignado (puede ser None si todavía no
      pasó por DeduplicatorEngine — está bien, se preserva tal cual).
    - Si es una publicación nueva, devuelve None a propósito: NO se
      crea/matchea un inmueble acá. Eso lo hace exclusivamente
      DeduplicatorEngine, con un criterio de matching más fino
      (ubicación + m² + dormitorios/baños + precio) que un hash barato.
    """
    return _buscar_publicacion_existente(conn, propiedad["portal"], propiedad["id_fuente"])


def _upsert_publicacion(conn: psycopg.Connection, propiedad: dict, inmueble_id: Optional[int]) -> bool:
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
                tipo_propiedad, precio, moneda,
                provincia, departamento, barrio, direccion, latitud, longitud,
                superficie_cubierta_m2, superficie_total_m2,
                ambientes, dormitorios, banios, cochera,
                fotos, foto_portada, fecha_extraccion
            ) VALUES (
                %(inmueble_id)s, %(fuente)s, %(id_fuente)s, %(url)s, %(titulo)s,
                %(tipo_operacion)s, %(tipo_propiedad)s, %(precio)s, %(moneda)s,
                %(provincia)s, %(departamento)s, %(barrio)s, %(direccion)s,
                %(latitud)s, %(longitud)s,
                %(superficie_cubierta_m2)s, %(superficie_total_m2)s,
                %(ambientes)s, %(dormitorios)s, %(banios)s, %(cochera)s,
                %(fotos)s, %(foto_portada)s, %(fecha_extraccion)s
            )
            ON CONFLICT (fuente, id_fuente) DO UPDATE SET
                precio                  = EXCLUDED.precio,
                moneda                  = EXCLUDED.moneda,
                titulo                  = EXCLUDED.titulo,
                tipo_propiedad          = EXCLUDED.tipo_propiedad,
                provincia               = EXCLUDED.provincia,
                departamento            = EXCLUDED.departamento,
                barrio                  = EXCLUDED.barrio,
                direccion               = EXCLUDED.direccion,
                latitud                 = EXCLUDED.latitud,
                longitud                = EXCLUDED.longitud,
                superficie_cubierta_m2  = EXCLUDED.superficie_cubierta_m2,
                superficie_total_m2     = EXCLUDED.superficie_total_m2,
                ambientes               = EXCLUDED.ambientes,
                dormitorios             = EXCLUDED.dormitorios,
                banios                  = EXCLUDED.banios,
                cochera                 = EXCLUDED.cochera,
                fotos                   = EXCLUDED.fotos,
                foto_portada            = EXCLUDED.foto_portada,
                fecha_extraccion        = EXCLUDED.fecha_extraccion,
                url                     = EXCLUDED.url
            RETURNING (xmax = 0) AS fue_insert
            """,
            {
                "inmueble_id": inmueble_id,
                "fuente": propiedad["portal"],
                "id_fuente": propiedad["id_fuente"],
                "url": propiedad["url_fuente"],
                "titulo": propiedad["titulo"],
                "tipo_operacion": propiedad["tipo_operacion"],
                "tipo_propiedad": propiedad.get("tipo_propiedad"),
                "precio": propiedad["precio"],
                "moneda": propiedad["moneda"],
                "provincia": propiedad.get("provincia", "Mendoza"),
                "departamento": propiedad.get("departamento"),
                "barrio": propiedad.get("barrio"),
                "direccion": propiedad.get("direccion"),
                "latitud": propiedad.get("latitud"),
                "longitud": propiedad.get("longitud"),
                "superficie_cubierta_m2": propiedad.get("superficie_cubierta_m2"),
                "superficie_total_m2": propiedad.get("superficie_total_m2"),
                "ambientes": propiedad.get("ambientes"),
                "dormitorios": propiedad.get("dormitorios"),
                "banios": propiedad.get("banios"),
                "cochera": propiedad.get("cochera"),
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
            inmueble_id = _resolver_inmueble_id(conn, propiedad)
            fue_insert = _upsert_publicacion(conn, propiedad, inmueble_id)
            conn.commit()

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
        "Guardado completo: %d publicaciones nuevas, %d actualizadas, %d errores. "
        "Corré DeduplicatorEngine para agrupar en inmuebles.",
        resultado.publicaciones_nuevas, resultado.publicaciones_actualizadas, resultado.errores,
    )
    return resultado
