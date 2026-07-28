import json
from scrapers.mercadolibre import MercadoLibreScraper

def main():
    print("=== Iniciando extracción de propiedades en Mendoza ===")
    
    scraper = MercadoLibreScraper()
    # Extraemos solo 1 página para probar
    propiedades = scraper.fetch_properties(max_pages=1)
    
    print(f"\n✅ Extracción completada. Total propiedades encontradas: {len(propiedades)}\n")
    
    # Mostramos las primeras 3 propiedades formateadas en JSON
    for prop in propiedades[:3]:
        print(json.dumps(prop.model_dump(), indent=2, ensure_ascii=False, default=str))
        print("-" * 50)

if __name__ == "__main__":
    main()