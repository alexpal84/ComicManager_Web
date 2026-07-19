from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseScraper(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str) -> List[Dict[str, Any]]:
        """Devuelve una lista de candidatos: {ref, title, series, year, publisher, ...}"""
        raise NotImplementedError

    @abstractmethod
    def get_details(self, ref: str) -> Dict[str, Any]:
        """Devuelve el detalle completo mapeado a los campos internos de Comic."""
        raise NotImplementedError
