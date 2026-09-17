"""
main.py
-------
Punto de entrada de Fase 1+2+3: ejecuta el scraper de Mercado Libre,
guarda las publicaciones en PostgreSQL y ejecuta el motor de
deduplicación para agrupar publicaciones en inmuebles canónicos.

Uso:
    python main.py
    python main.py --max 100 --query "casa venta mendoza"
    python main.py --sin-dedup          # solo scraping + guardado
"""

import argparse
import json
import os

from config import DATA_DIR, ML_SLUG_BUSQUEDA, MAX_PAGINAS_POR_DEFECTO, get_logger
from scrapers.mercadolibre import MercadoLibreScraper

logger = get_logger("main")


def main():
    parser = argparse.ArgumentParser(description="Extractor Fase 1+2 - Mercado Libre Inmuebles Mendoza")
    parser.add_argument(
        "--paginas", type=int, default=MAX_PAGINAS_POR_DEFECTO,
        help="Cantidad de páginas de resultados a recorrer (~48 propiedades por página)",
    )
    parser.add_argument(
        "--slug", type=str, default=ML_SLUG_BUSQUEDA,
        help="Slug de búsqueda de ML, ej: 'departamentos-venta-mendoza' o 'casas-venta-mendoza'",
    )
    parser.add_argument(
        "--visible", action="store_true",
        help="Mostrar el navegador (no headless) — útil para depurar si algo falla",
    )
    parser.add_argument(
        "--sin-db", action="store_true",
        help="No guardar en PostgreSQL, solo generar el JSON (útil para probar el scraper solo)",
    )
    parser.add_argument(
        "--sin-json", action="store_true",
        help="No generar el archivo JSON, solo guardar en la base de datos",
    )
    parser.add_argument(
        "--sin-dedup", action="store_true",
        help="No ejecutar el motor de deduplicación (solo scraping + guardado)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=os.path.join(DATA_DIR, "propiedades_mercadolibre.json"),
        help="Archivo de salida JSON",
    )
    args = parser.parse_args()

    logger.info("Iniciando extracción: slug='%s', paginas=%d", args.slug, args.paginas)

    with MercadoLibreScraper(slug=args.slug, headless=not args.visible) as scraper:
        propiedades = scraper.extraer(max_paginas=args.paginas)

    if not args.sin_json:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(propiedades, f, ensure_ascii=False, indent=2)
        logger.info("Guardadas %d propiedades en %s", len(propiedades), args.output)
        print(f"✅ JSON: {len(propiedades)} propiedades guardadas en {args.output}")

    if not args.sin_db:
        # Import diferido: así `python main.py --sin-db` no requiere
        # tener psycopg instalado ni PostgreSQL corriendo.
        from db.connection import obtener_conexion
        from db.repository import guardar_propiedades

        with obtener_conexion() as conn:
            resultado = guardar_propiedades(conn, propiedades)

        print(
            f"✅ DB: {resultado.publicaciones_nuevas} publicaciones nuevas, "
            f"{resultado.publicaciones_actualizadas} actualizadas"
            + (f" | ⚠️ {resultado.errores} errores" if resultado.errores else "")
        )

        if not args.sin_dedup:
            from services.deduplicator import DeduplicatorEngine

            with obtener_conexion() as conn:
                dedup = DeduplicatorEngine(conn)
                resultado_dedup = dedup.ejecutar()

            print(
                f"🔗 Deduplicación: {resultado_dedup.publicaciones_asignadas} "
                f"publicaciones asignadas, "
                f"{resultado_dedup.inmuebles_creados} inmuebles creados, "
                f"{resultado_dedup.inmuebles_reutilizados} reutilizados"
                + (f" | ⚠️ {resultado_dedup.errores} errores" if resultado_dedup.errores else "")
            )


if __name__ == "__main__":
    main()
