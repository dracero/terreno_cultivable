import logging
from typing import Dict, Any, Optional
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score
from ..config import JEV_API_KEY

logger = logging.getLogger(__name__)

class JevService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or JEV_API_KEY

    async def evaluate_system_one(
        self,
        state: Dict[str, Any],
        questions: Dict[str, Any]
    ) -> Any:
        """
        Ejecuta una evaluación System One de Jev con estado estructurado y preguntas tipadas.
        """
        if not self.api_key:
            raise ValueError("No se ha configurado JEV_API_KEY o TYPESAFE_API_KEY")

        async with AsyncTypeSafeClient(api_key=self.api_key) as client:
            response = await client.system_one(
                state=state,
                questions=questions
            )
            return response

# Instancia singleton
jev_service = JevService()
