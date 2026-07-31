"""
main.py
-------
Punto de entrada de Fase 1: ejecuta el scraper de Mercado Libre y
guarda el resultado normalizado en data/propiedades_mercadolibre.json

Uso:
    python main.py
    python main.py --max 100 --query "casa venta mendoza"
"""

import argparse
import json
import os

from config import DATA_DIR, ML_SLUG_BUSQUEDA, MAX_PAGINAS_POR_DEFECTO, get_logger
from scrapers.mercadolibre import MercadoLibreScraper

logger = get_logger("main")


def main():
    parser = argparse.ArgumentParser(description="Extractor Fase 1 - Mercado Libre Inmuebles Mendoza")
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
        "--output",
        type=str,
        default=os.path.join(DATA_DIR, "propiedades_mercadolibre.json"),
        help="Archivo de salida",
    )
    args = parser.parse_args()

    logger.info("Iniciando extracción: slug='%s', paginas=%d", args.slug, args.paginas)

    with MercadoLibreScraper(slug=args.slug, headless=not args.visible) as scraper:
        propiedades = scraper.extraer(max_paginas=args.paginas)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(propiedades, f, ensure_ascii=False, indent=2)

    logger.info("Guardadas %d propiedades en %s", len(propiedades), args.output)
    print(f"\n✅ Listo. {len(propiedades)} propiedades guardadas en: {args.output}")


if __name__ == "__main__":
    main()