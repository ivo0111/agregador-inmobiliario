from pydantic import BaseModel, HttpUrl
from typing import Optional, List
from datetime import datetime

class Property(BaseModel):
    id_fuente: str                  # ID único del portal de origen
    fuente: str                     # Ej: 'mercadolibre', 'zonaprop'
    titulo: str
    precio: Optional[float] = None
    moneda: Optional[str] = None     # 'USD' o 'ARS'
    ubicacion: Optional[str] = None  # Ej: 'Capital, Mendoza'
    superficie_total_m2: Optional[float] = None
    superficie_cubierta_m2: Optional[float] = None
    ambientes: Optional[int] = None
    dormitorios: Optional[int] = None
    banos: Optional[int] = None
    url_fuente: str
    fotos: List[str] = []
    fecha_extraccion: datetime = datetime.utcnow()