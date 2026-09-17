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

import os
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
    MAX_REINTENTOS_POR_PAGINA,
    DELAY_ENTRE_PAGINAS_SEGUNDOS,
    USER_AGENTS,
    VIEWPORTS,
    STORAGE_STATE_PATH,
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
        self._browser = self._playwright.chromium.launch(headless=self.headless)

        # Rotación de viewport: elige uno al azar para no tener fingerprint fijo.
        viewport = random.choice(VIEWPORTS)

        # Contexto con user-agent realista y locale argentino.
        self._context = self._browser.new_context(
            viewport=viewport,
            locale="es-AR",
            user_agent=random.choice(USER_AGENTS),
            # Guardar/cargar cookies de sesiones anteriores para parecer
            # un usuario que ya visitó ML antes (reduce sospecha de bot).
            storage_state=STORAGE_STATE_PATH if os.path.exists(STORAGE_STATE_PATH) else None,
        )

        # Headers HTTP que un Chrome real envía en cada request.
        self._context.set_extra_http_headers({
            "Accept-Language": "es-AR,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "sec-ch-ua": '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
        })

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Guardar cookies/estado de sesión para reutilizar en la próxima ejecución.
        if self._context:
            try:
                self._context.storage_state(path=STORAGE_STATE_PATH)
            except Exception:
                pass
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
                    # "networkidle" espera a que pare el tráfico de red (JS renderizado completo).
                    page.goto(url, wait_until="networkidle")
                except Exception as exc:
                    logger.error("No se pudo cargar %s: %s", url, exc)
                    break

                # Reintento: si ML devolvió la página de error, reintentar una vez
                # después de una pausa más larga (puede ser un rate-limit temporal).
                if self._es_pagina_error(page):
                    logger.warning("ML devolvió página de error en intento 1, reintentando...")
                    time.sleep(random.uniform(5.0, 8.0))
                    try:
                        page.goto(url, wait_until="networkidle")
                    except Exception as exc:
                        logger.error("No se pudo recargar %s en reintento: %s", url, exc)
                        break
                    if self._es_pagina_error(page):
                        logger.error("ML sigue devolviendo error después de reintento en %s", url)
                        self._guardar_debug(page, f"error_bloqueo_pagina_{num_pagina + 1}")
                        break

                # Esperar explícitamente a que aparezca al menos una card en el DOM.
                # Si no aparecen en 15s, probablemente es la página de error o no hay resultados.
                try:
                    primer_selector = self._esperar_cards(page)
                except Exception:
                    primer_selector = None

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
        # Fix (confirmado empíricamente): la paginación real de ML
        # requiere este formato exacto, con la barra y "_NoIndex_True"
        # al final — sin eso, ML devuelve siempre la página 1 aunque el
        # offset cambie (el scraper "creía" avanzar pero repetía datos).
        return f"{ML_LISTADO_BASE}/{self.slug}/_Desde_{offset + 1}_NoIndex_True"

    def _es_pagina_error(self, page: Page) -> bool:
        """
        Detecta si ML devolvió la página genérica de error
        ("Hubo un error accediendo a esta pagina...") en vez del listado.
        Es un indicador de rate-limit o bloqueo anti-bot.
        """
        try:
            error_marker = page.query_selector("div.ui-empty-state.not-found-page")
            return error_marker is not None
        except Exception:
            return False

    def _esperar_cards(self, page: Page) -> Optional[str]:
        """
        Espera explícitamente a que aparezca al menos una card en el DOM.
        Devuelve el selector que matcheó, o None si ninguno apareció.
        Esto le da tiempo a ML para renderizar el JS completo.
        """
        for selector in SELECTORES_CARD:
            try:
                page.wait_for_selector(selector, timeout=15_000)
                return selector
            except Exception:
                continue
        return None

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
