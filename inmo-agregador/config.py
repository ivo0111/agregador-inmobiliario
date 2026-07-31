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
#   https://listado.mercadolibre.com.ar/{slug}
# ej: https://listado.mercadolibre.com.ar/departamentos-venta-mendoza
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

# Delay entre cargas de página. Es clave para no parecer un bot agresivo
# y no saturar el servidor. NO bajar esto para "ir más rápido": es la
# diferencia entre un scraper sostenible y uno que termina bloqueado.
DELAY_ENTRE_PAGINAS_SEGUNDOS = (2.5, 5.0)  # rango para randomizar (min, max)

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