import httpx
from bs4 import BeautifulSoup
import re
from typing import List, Optional
from models.models import Property
from scrapers.base import BaseScraper

class MercadoLibreScraper(BaseScraper):
    BASE_URL = "https://inmuebles.mercadolibre.com.ar/venta/mendoza/"
    
    # Encabezados más realistas para simular un navegador real
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"macOS"',
    }

    def __init__(self):
        super().__init__(nombre_fuente="mercadolibre")

    def _parse_item(self, item: BeautifulSoup) -> Optional[Property]:
        try:
            # Enlace / Título - Probamos múltiples selectores posibles
            link_tag = item.find("a", class_=re.compile(r"ui-search-link|poly-component__title|ui-search-result__content")) or item.find("a")
            if not link_tag or not link_tag.get("href"):
                return None
            
            url_fuente = link_tag.get("href")
            titulo = link_tag.text.strip() if link_tag.text else "Sin título"

            # ID de fuente
            id_match = re.search(r"MLA-?(\d+)", url_fuente)
            id_fuente = id_match.group(1) if id_match else url_fuente

            # Precio y Moneda (Búsqueda más flexible)
            precio_container = item.find("div", class_=re.compile(r"ui-search-price|poly-price|andes-money-amount")) or item
            moneda_tag = precio_container.find("span", class_=re.compile(r"symbol|currency"))
            precio_tag = precio_container.find("span", class_=re.compile(r"fraction|amount"))
            
            moneda = moneda_tag.text.strip() if moneda_tag else None
            if moneda == "$":
                moneda = "ARS"
            elif moneda in ["U$S", "USD", "US$"]:
                moneda = "USD"

            precio = None
            if precio_tag:
                raw_precio = re.sub(r"[^\d]", "", precio_tag.text)
                if raw_precio:
                    precio = float(raw_precio)

            # Ubicación
            ubicacion_tag = item.find("span", class_=re.compile(r"location|poly-component__location"))
            ubicacion = ubicacion_tag.text.strip() if ubicacion_tag else "Mendoza"

            # Atributos (m², dormitorios)
            attributes = item.find_all(["li", "span"], class_=re.compile(r"attribute|attributes|poly-component__attribute"))
            m2_total = None
            dormitorios = None
            ambientes = None

            for attr in attributes:
                text = attr.text.lower()
                if "m²" in text:
                    num = re.search(r"(\d+)", text)
                    if num:
                        m2_total = float(num.group(1))
                elif "dorm" in text or "hab" in text:
                    num = re.search(r"(\d+)", text)
                    if num:
                        dormitorios = int(num.group(1))
                elif "amb" in text:
                    num = re.search(r"(\d+)", text)
                    if num:
                        ambientes = int(num.group(1))

            # Imagen principal
            img_tag = item.find("img")
            foto_url = None
            if img_tag:
                foto_url = img_tag.get("data-src") or img_tag.get("src")
            fotos = [foto_url] if foto_url else []

            return Property(
                id_fuente=str(id_fuente),
                fuente=self.nombre_fuente,
                titulo=titulo,
                precio=precio,
                moneda=moneda,
                ubicacion=ubicacion,
                superficie_total_m2=m2_total,
                dormitorios=dormitorios,
                ambientes=ambientes,
                url_fuente=url_fuente,
                fotos=fotos
            )

        except Exception as e:
            print(f"Error parseando item: {e}")
            return None

    def fetch_properties(self, max_pages: int = 1) -> List[Property]:
        properties: List[Property] = []
        
        with httpx.Client(headers=self.HEADERS, follow_redirects=True, timeout=15.0) as client:
            for page in range(1, max_pages + 1):
                offset = (page - 1) * 48 + 1
                url = f"{self.BASE_URL}_Desde_{offset}" if page > 1 else self.BASE_URL
                
                print(f"Obteniendo datos de: {url}")
                response = client.get(url)
                
                if response.status_code != 200:
                    print(f"❌ Error HTTP {response.status_code} al acceder a la página {page}")
                    break

                soup = BeautifulSoup(response.text, "html.parser")
                
                # Buscamos los contenedores con múltiples estrategias (ML actualiza su UI seguido)
                items = soup.find_all("li", class_=re.compile(r"ui-search-layout__item|ui-search-result"))
                if not items:
                    # Intento secundario: buscar tarjetas genéricas de resultados (UI nueva de ML 'poly-card')
                    items = soup.find_all("div", class_=re.compile(r"poly-card|ui-search-result__wrapper"))

                print(f"🔍 Elementos encontrados en el HTML: {len(items)}")

                for item in items:
                    prop = self._parse_item(item)
                    if prop:
                        properties.append(prop)

        return properties