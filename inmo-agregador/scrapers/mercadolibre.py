"""
scrapers/mercadolibre.py
------------------------
Extractor de publicaciones de "Venta de Departamentos" en Mendoza desde
Mercado Libre.

CAMBIO DE ARQUITECTURA (importante, leer antes de tocar este archivo):
La versión anterior usaba la API pública `/sites/MLA/search`, pero
Mercado Libre restringió ese endpoint y ahora devuelve 403 sin
autenticación OAuth (confirmado: varios proyectos de terceros tuvieron
que dar de baja sus integraciones de búsqueda por este motivo, ver
README). Por eso esta versión navega directamente las páginas públicas
de resultados con Playwright (el contenido se carga con JS, así que un
simple `httpx.get` no alcanza).

ADVERTENCIA SOBRE ESTABILIDAD:
Scrapear HTML es inherentemente más frágil que una API: si Mercado Libre
cambia los nombres de clases CSS, este código puede dejar de encontrar
resultados de un día para el otro. Por eso:
  1. Los selectores están definidos como LISTAS de candidatos (se prueba
     el primero que matchee algo), no como un único string mágico.
  2. Si en una página no se encuentra ningún resultado, se guarda el
     HTML crudo en debug/ para poder inspeccionarlo y ajustar selectores
     rápido, en vez de fallar en silencio.
  3. Hay delays randomizados entre páginas para no golpear el servidor
     de forma agresiva ni parecer tráfico de bot.
"""

import random
import re
import time
from typing import Optional

from playwright.sync_api import sync_playwright, Page, ElementHandle

from config import (
    ML_LISTADO_BASE,
    ML_SLUG_BUSQUEDA,
    ML_RESULTADOS_POR_PAGINA,
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_TIMEOUT_MS,
    MAX_PAGINAS_POR_DEFECTO,
    DELAY_ENTRE_PAGINAS_SEGUNDOS,
    DEBUG_DIR,
    get_logger,
)
from schema import Propiedad
from scrapers.utils.normalizador import (
    extraer_atributos_desde_texto,
    extraer_precio_moneda,
    extraer_ubicacion_desde_texto,
)

logger = get_logger("scraper.mercadolibre")

# Selectores candidatos para la card de cada publicación en el listado.
# Mercado Libre tiene (al momento de escribir esto) dos "familias" de
# markup conviviendo: el legado "ui-search-*" y el rediseño "poly-card*".
# Probamos ambos por las dudas.
SELECTORES_CARD = [
    "li.ui-search-layout__item",
    "div.ui-search-result",
    "div.poly-card",
    "div[class*='poly-card']",
]

SELECTORES_TITULO = [
    "h2.poly-component__title",
    "h2.ui-search-item__title",
    "a.poly-component__title",
    "h2",
]

SELECTORES_PRECIO = [
    "span.andes-money-amount",
    "div.poly-price__current span.andes-money-amount",
]

SELECTORES_LINK = [
    "a.poly-component__title",
    "a.ui-search-link",
    "a.poly-card__link",
    "a",
]

SELECTORES_UBICACION = [
    "span.poly-component__location",
    "span.ui-search-item__location",
]

SELECTORES_IMAGEN = [
    "img.poly-component__picture",
    "img.ui-search-result-image__element",
    "img",
]


class MercadoLibreScraper:
    """
    Encapsula la extracción vía Playwright del listado público de
    Mercado Libre Inmuebles para Mendoza.

    Uso:
        with MercadoLibreScraper() as scraper:
            propiedades = scraper.extraer(max_paginas=5)
    """

    def __init__(self, slug: str = ML_SLUG_BUSQUEDA, headless: bool = PLAYWRIGHT_HEADLESS):
        self.slug = slug
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None

    def __enter__(self):
        self._playwright = sync_playwright().start()
        # Headless=False es útil en desarrollo para VER qué está pasando
        # si algo no matchea; en producción/servidor dejar en True.
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context(
            viewport={"width": 1366, "height": 900},
            locale="es-AR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
        )
        # Inyectar scripts ANTES de que la página cargue para evitar
        # la detección de webdriver por parte de MercadoLibre.
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'languages', { get: () => ['es-AR', 'es', 'en'] });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            window.chrome = { runtime: {} };
        """)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    # ------------------------------------------------------------------ #
    # Métodos públicos
    # ------------------------------------------------------------------ #

    def extraer(self, max_paginas: int = MAX_PAGINAS_POR_DEFECTO) -> list[dict]:
        propiedades: list[dict] = []
        page = self._context.new_page()
        page.set_default_timeout(PLAYWRIGHT_TIMEOUT_MS)

        try:
            for num_pagina in range(max_paginas):
                offset = num_pagina * ML_RESULTADOS_POR_PAGINA
                url = self._construir_url(offset)
                logger.info("Cargando página %d: %s", num_pagina + 1, url)

                try:
                    # Usamos commit para no quedarnos bloqueados en el challenge
                    # anti-bot de ML. Después esperamos networkidle para darle
                    # tiempo al JS de la página de resolverse y redirigir.
                    page.goto(url, wait_until="commit", timeout=PLAYWRIGHT_TIMEOUT_MS)
                    try:
                        page.wait_for_load_state("networkidle", timeout=20_000)
                    except Exception:
                        logger.debug("Timeout esperando networkidle, continuando de todos modos")
                except Exception as exc:
                    logger.error("No se pudo cargar %s: %s", url, exc)
                    break

                # Pequeña espera adicional para que el DOM se estabilice
                # después del challenge/redirect.
                page.wait_for_timeout(2000)

                cards = self._buscar_cards(page)

                if not cards:
                    logger.warning(
                        "No se encontraron resultados en %s. "
                        "Guardando HTML de debug para inspección.",
                        url,
                    )
                    self._guardar_debug(page, f"sin_resultados_pagina_{num_pagina + 1}")
                    break

                logger.info("Encontradas %d cards en la página %d", len(cards), num_pagina + 1)

                for card in cards:
                    try:
                        propiedad = self._parsear_card(card)
                        if propiedad:
                            propiedades.append(propiedad.to_dict())
                    except Exception as exc:
                        logger.warning("No se pudo parsear una card: %s", exc)

                # Delay randomizado entre páginas — no bajar esto.
                time.sleep(random.uniform(*DELAY_ENTRE_PAGINAS_SEGUNDOS))

        finally:
            page.close()

        logger.info("Extracción finalizada: %d propiedades procesadas.", len(propiedades))
        return propiedades

    # ------------------------------------------------------------------ #
    # Internos
    # ------------------------------------------------------------------ #

    def _construir_url(self, offset: int) -> str:
        if offset == 0:
            return f"{ML_LISTADO_BASE}/{self.slug}"
        # ML pagina con "_Desde_{N}" donde N es 1-indexed (1, 49, 97, ...)
        return f"{ML_LISTADO_BASE}/{self.slug}/_Desde_{offset + 1}_NoIndex_True"

    def _buscar_cards(self, page: Page) -> list[ElementHandle]:
        for selector in SELECTORES_CARD:
            elementos = page.query_selector_all(selector)
            if elementos:
                logger.debug("Selector de card usado: %s (%d encontrados)", selector, len(elementos))
                return elementos
        return []

    def _primer_texto(self, card: ElementHandle, selectores: list[str]) -> Optional[str]:
        for selector in selectores:
            elemento = card.query_selector(selector)
            if elemento:
                texto = elemento.text_content()
                if texto and texto.strip():
                    return texto.strip()
        return None

    def _primer_atributo(self, card: ElementHandle, selectores: list[str], atributo: str) -> Optional[str]:
        for selector in selectores:
            elemento = card.query_selector(selector)
            if elemento:
                valor = elemento.get_attribute(atributo)
                if valor:
                    return valor
        return None

    def _extraer_id_desde_url(self, url: str) -> str:
        # Los permalinks de ML tienen el ID de publicación en la ruta,
        # ej: .../MLA-1234567890-departamento-.../ -> "MLA1234567890"
        match = re.search(r"MLA-?(\d+)", url or "")
        return f"MLA{match.group(1)}" if match else (url or "")[-40:]

    def _parsear_card(self, card: ElementHandle) -> Optional[Propiedad]:
        titulo = self._primer_texto(card, SELECTORES_TITULO)
        url_fuente = self._primer_atributo(card, SELECTORES_LINK, "href")
        precio_texto = self._primer_texto(card, SELECTORES_PRECIO)
        ubicacion_texto = self._primer_texto(card, SELECTORES_UBICACION)
        imagen_url = self._primer_atributo(card, SELECTORES_IMAGEN, "src") or \
            self._primer_atributo(card, SELECTORES_IMAGEN, "data-src")

        if not titulo or not url_fuente:
            # Sin título o sin link no hay publicación válida que guardar.
            return None

        # Texto completo de la card como respaldo para extraer atributos
        # (ambientes, m2, etc.) que a veces no están en un span aparte.
        texto_completo = card.text_content() or ""

        precio_info = extraer_precio_moneda(precio_texto or texto_completo)
        atributos = extraer_atributos_desde_texto(texto_completo)
        ubicacion = extraer_ubicacion_desde_texto(ubicacion_texto or "")

        return Propiedad(
            id_fuente=self._extraer_id_desde_url(url_fuente),
            portal="mercadolibre",
            url_fuente=url_fuente,
            titulo=titulo,
            tipo_operacion="venta",
            tipo_propiedad="departamento",  # fijo en esta fase: el slug ya filtra por departamentos
            precio=precio_info["precio"],
            moneda=precio_info["moneda"],
            provincia="Mendoza",
            departamento=ubicacion["departamento"],
            barrio=ubicacion["barrio"],
            direccion=ubicacion["direccion"],
            superficie_cubierta_m2=atributos["superficie_cubierta_m2"],
            superficie_total_m2=atributos["superficie_total_m2"],
            ambientes=atributos["ambientes"],
            dormitorios=atributos["dormitorios"],
            banios=atributos["banios"],
            cochera=atributos["cochera"],
            fotos=[imagen_url] if imagen_url else [],
            foto_portada=imagen_url,
        )

    def _guardar_debug(self, page: Page, nombre: str) -> None:
        """
        Vuelca el HTML y una captura de pantalla a debug/ para poder
        inspeccionar qué está devolviendo ML cuando los selectores no
        encuentran nada (ej: cambiaron el markup, o mostraron un
        challenge anti-bot / captcha).
        """
        try:
            html_path = f"{DEBUG_DIR}/{nombre}.html"
            screenshot_path = f"{DEBUG_DIR}/{nombre}.png"
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(page.content())
            page.screenshot(path=screenshot_path, full_page=True)
            logger.info("Debug guardado en %s y %s", html_path, screenshot_path)
        except Exception as exc:
            logger.warning("No se pudo guardar debug: %s", exc)