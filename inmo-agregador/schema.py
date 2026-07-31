"""
schema.py
---------
Define la estructura estandarizada (JSON/dict) en la que se normalizan
las propiedades extraídas de CUALQUIER portal (Mercado Libre, Zonaprop,
Argenprop, inmobiliarias locales, etc.).
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional
import hashlib


@dataclass
class Propiedad:
    id_fuente: str
    portal: str
    url_fuente: str
    titulo: str
    tipo_operacion: str = "venta"
    tipo_propiedad: Optional[str] = None
    precio: Optional[float] = None
    moneda: Optional[str] = None
    provincia: str = "Mendoza"
    departamento: Optional[str] = None
    barrio: Optional[str] = None
    direccion: Optional[str] = None
    latitud: Optional[float] = None
    longitud: Optional[float] = None
    superficie_cubierta_m2: Optional[float] = None
    superficie_total_m2: Optional[float] = None
    ambientes: Optional[int] = None
    dormitorios: Optional[int] = None
    banios: Optional[int] = None
    cochera: Optional[bool] = None
    fotos: list = field(default_factory=list)
    foto_portada: Optional[str] = None
    fecha_extraccion: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    hash_duplicado: Optional[str] = None

    def __post_init__(self):
        base = f"{self.tipo_propiedad}|{self.barrio}|{self.superficie_cubierta_m2}|{round(self.precio or 0, -3)}"
        self.hash_duplicado = hashlib.md5(base.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)


DEPARTAMENTOS_MENDOZA = [
    "Capital", "Godoy Cruz", "Guaymallén", "Las Heras", "Luján de Cuyo",
    "Maipú", "Junín", "Rivadavia", "San Martín", "Santa Rosa", "La Paz",
    "General Alvear", "San Rafael", "Malargüe", "Tunuyán", "Tupungato",
    "San Carlos", "Lavalle",
]
