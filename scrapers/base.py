from abc import ABC, abstractmethod
from typing import List
from models.models import Property

class BaseScraper(ABC):
    def __init__(self, nombre_fuente: str):
        self.nombre_fuente = nombre_fuente

    @abstractmethod
    def fetch_properties(self, max_pages: int = 1) -> List[Property]:
        """Método que debe implementar cada scraper específico para extraer propiedades."""
        pass