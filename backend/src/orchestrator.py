import time
import logging
from .schemas import AnalyzeRequest, MultiAgentAnalysisResult
from .agents.geo_extractor import GeoExtractorAgent
from .agents.hydro_risk import HydroRiskAgent
from .agents.agro_verdict import AgroVerdictAgent

logger = logging.getLogger(__name__)

class MultiAgentOrchestrator:
    """
    Orquestador del pipeline multiagente:
    1. Agente 1: GeoExtractorAgent (Microsoft Planetary Computer STAC)
    2. Agente 2: HydroRiskAgent (JEV System One: Noul, Score, Choice)
    3. Agente 3: AgroVerdictAgent (JEV System One: Choice, Score, Noul)
    """
    def __init__(self):
        self.agent1 = GeoExtractorAgent()
        self.agent2 = HydroRiskAgent()
        self.agent3 = AgroVerdictAgent()

    async def run(self, request: AnalyzeRequest) -> MultiAgentAnalysisResult:
        total_start = time.perf_counter()
        traces = []

        logger.info(f"=== Iniciando Pipeline Multiagente para ({request.lat}, {request.lon}) ===")

        # Paso 1: Extracción Geoespacial
        geo_state, trace1 = await self.agent1.execute(request)
        traces.append(trace1)

        # Paso 2: Evaluación de Riesgo Hidrológico con JEV
        hydro_profile, trace2 = await self.agent2.execute(geo_state)
        traces.append(trace2)

        # Paso 3: Dictamen de Aptitud Agronómica con JEV
        verdict, trace3 = await self.agent3.execute(geo_state, hydro_profile)
        traces.append(trace3)

        total_elapsed_ms = round((time.perf_counter() - total_start) * 1000, 2)
        logger.info(f"=== Pipeline Multiagente Completado en {total_elapsed_ms} ms ===")

        return MultiAgentAnalysisResult(
            request=request,
            geospatial=geo_state,
            hydro_risk=hydro_profile,
            verdict=verdict,
            traces=traces,
            execution_time_total_ms=total_elapsed_ms
        )

orchestrator = MultiAgentOrchestrator()
