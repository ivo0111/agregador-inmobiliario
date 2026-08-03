"""
schema.py
---------
Define la estructura estandarizada (JSON/dict) en la que se normalizan
las propiedades extraídas de CUALQUIER portal (Mercado Libre, Zonaprop,
Argenprop, inmobiliarias locales, etc.).

Todos los scrapers, sin importar la fuente, deben devolver una lista de
diccionarios con exactamente esta forma. Esto es lo que permite que en
Fase 2 (base de datos) todo entre a una única tabla `propiedades` sin
importar de dónde vino.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
import hashlib


@dataclass
class Propiedad:
    # --- Identificación ---
    id_fuente: str                 # ID original en el portal (ej: "MLA123456789")
    portal: str                    # "mercadolibre", "zonaprop", "argenprop", etc.
    url_fuente: str                # link directo a la publicación

    # --- Datos comerciales ---
    titulo: str
    tipo_operacion: str = "venta"  # venta | alquiler (por ahora solo venta)
    tipo_propiedad: Optional[str] = None  # departamento | casa | terreno | ph | local, etc.
    precio: Optional[float] = None
    moneda: Optional[str] = None   # "USD" | "ARS"

    # --- Ubicación ---
    provincia: str = "Mendoza"
    departamento: Optional[str] = None   # ej: "Godoy Cruz", "Ciudad", "Luján de Cuyo"
    barrio: Optional[str] = None
    direccion: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None

    # --- Características físicas ---
    superficie_cubierta_m2: Optional[float] = None
    superficie_total_m2: Optional[float] = None
    ambientes: Optional[int] = None
    dormitorios: Optional[int] = None
    banios: Optional[int] = None
    cochera: Optional[bool] = None

    # --- Multimedia ---
    fotos: list = field(default_factory=list)   # lista de URLs
    foto_portada: Optional[str] = None

    # --- Metadata de control ---
    fecha_extraccion: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hash_duplicado: Optional[str] = None  # se calcula en __post_init__

    def __post_init__(self):
        # Hash simple para detectar posibles duplicados entre portales:
        # combina tipo, barrio y superficie.
        #
        # OJO: el precio queda deliberadamente AFUERA del hash. Es el
        # campo más volátil (cambia entre re-scrapeos de la misma
        # publicación, y puede diferir levemente entre portales por
        # comisión/redondeo/conversión de moneda). Incluirlo rompía el
        # matching: re-scrapear la misma publicación con precio
        # actualizado generaba un "inmueble fantasma" duplicado.
        #
        # Esto NO es definitivo (se refina en Fase 3+ con matching
        # geoespacial y/o similitud de texto), pero sirve como primer
        # filtro barato.
        base = f"{self.tipo_propiedad}|{self.barrio}|{self.superficie_cubierta_m2}"
        self.hash_duplicado = hashlib.md5(base.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


# Mapeo de barrios/zonas de Mendoza usados para normalizar texto libre
# (los portales escriben "Chacras de Coria, Luján de Cuyo" de mil formas distintas).
DEPARTAMENTOS_MENDOZA = [
    "Capital", "Godoy Cruz", "Guaymallén", "Las Heras", "Luján de Cuyo",
    "Maipú", "Junín", "Rivadavia", "San Martín", "Santa Rosa", "La Paz",
    "General Alvear", "San Rafael", "Malargüe", "Tunuyán", "Tupungato",
    "San Carlos", "Lavalle",
]
