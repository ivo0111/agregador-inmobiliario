"""
config.py
---------
Configuración centralizada. Nada de "magic numbers" o URLs sueltas
dentro de los scrapers: todo vive acá para que sea fácil de mantener
cuando agreguemos más portales en las próximas fases.
"""

import logging
import os

# --- Rutas ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
DEBUG_DIR = os.path.join(BASE_DIR, "debug")  # HTML/screenshots crudos si algo falla

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(DEBUG_DIR, exist_ok=True)

# --- Mercado Libre ---
# IMPORTANTE (actualizado): Mercado Libre restringió el acceso público
# no autenticado a su API de búsqueda (/sites/{site}/search) — devuelve
# 403 desde 2025. Varias apps de terceros confirman que tuvieron que dar
# de baja sus integraciones de búsqueda por este motivo. Por eso esta
# fase scrapea directamente las páginas públicas de resultados con
# Playwright (contenido cargado por JS), en vez de pegarle a la API.
#
# URL de listado confirmada funcionando (sin login):
#   https://inmuebles.mercadolibre.com.ar/{slug}/_Desde_{N}_NoIndex_True
# (el dominio "listado.mercadolibre.com.ar" también carga la página 1,
# pero la paginación real vive en el subdominio "inmuebles.")
ML_LISTADO_BASE = "https://inmuebles.mercadolibre.com.ar"
ML_SLUG_BUSQUEDA = "departamentos-venta-mendoza"

# Mercado Libre pagina agregando "_Desde_{N}" a la URL, donde N es el
# número de resultado inicial (1, 51, 101, ...). Si en el futuro cambian
# este esquema, el scraper cae a navegar por el botón "Siguiente".
ML_RESULTADOS_POR_PAGINA = 48  # observado en la práctica; puede variar

# --- Playwright / scraping general ---
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT_MS = 20_000
MAX_PAGINAS_POR_DEFECTO = 5
MAX_REINTENTOS_POR_PAGINA = 1  # reintentos si ML devuelve la página de error

# Delay entre cargas de página. Es clave para no parecer un bot agresivo
# y no saturar el servidor. NO bajar esto para "ir más rápido": es la
# diferencia entre un scraper sostenible y uno que termina bloqueado.
DELAY_ENTRE_PAGINAS_SEGUNDOS = (2.5, 5.0)  # rango para randomizar (min, max)

# --- Anti-detección ---
# User-Agents reales de Chrome (actualizados periodicamente). Playwright
# por defecto envía "HeadlessChrome" que ML detecta al toque.
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]

# Viewports comunes de escritorio para rotar el fingerprint.
VIEWPORTS = [
    {"width": 1366, "height": 768},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1920, "height": 1080},
    {"width": 1280, "height": 720},
]

# Path para persistir cookies/estado de sesión de Playwright entre páginas.
STORAGE_STATE_PATH = os.path.join(BASE_DIR, "debug", "ml_storage_state.json")

# --- Logging ---
LOG_LEVEL = logging.INFO
LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def get_logger(nombre: str) -> logging.Logger:
    logger = logging.getLogger(nombre)
    if not logger.handlers:
        logger.setLevel(LOG_LEVEL)
        formatter = logging.Formatter(LOG_FORMAT)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        file_handler = logging.FileHandler(
            os.path.join(LOGS_DIR, "scraper.log"), encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger
