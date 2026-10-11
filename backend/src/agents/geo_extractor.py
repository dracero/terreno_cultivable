import time
import logging
from ..schemas import AnalyzeRequest, GeospatialState, AgentExecutionTrace
from ..services.planetary_stac import query_planetary_stac

logger = logging.getLogger(__name__)

class GeoExtractorAgent:
    """
    Agente 1: Ingesta y Extracción Geoespacial.
    Consulta la API STAC de Microsoft Planetary Computer (JRC Global Surface Water,
    Copernicus DEM, Sentinel-1 y Sentinel-2) para estructurar el estado biofísico de la parcela.
    """
    def __init__(self):
        self.name = "GeoExtractorAgent (Planetary Computer STAC)"

    async def execute(self, request: AnalyzeRequest) -> tuple[GeospatialState, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Consultando STAC para coordenadas ({request.lat}, {request.lon})...")

        stac_data = await query_planetary_stac(request.lat, request.lon)

        state = GeospatialState(
            parcel_name=request.parcel_name or "Parcela Rural",
            lat=request.lat,
            lon=request.lon,
            bbox=stac_data["bbox"],
            elevation_m=stac_data["elevation_m"],
            slope_deg=stac_data["slope_deg"],
            relative_depression_score=stac_data["relative_depression_score"],
            jrc_occurrence_pct=stac_data["jrc_occurrence_pct"],
            jrc_max_extent=stac_data["jrc_max_extent"],
            jrc_seasonality=stac_data["jrc_seasonality"],
            sar_backscatter_db=stac_data["sar_backscatter_db"],
            sentinel2_ndwi=stac_data["sentinel2_ndwi"],
            stac_items_found=stac_data["stac_items_found"],
            tile_layers=stac_data["tile_layers"],
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace = AgentExecutionTrace(
            agent_id="agent_1_geo_extractor",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "cota_msnm": f"{state.elevation_m} m",
                "pendiente": f"{state.slope_deg}°",
                "jrc_agua_pct": f"{state.jrc_occurrence_pct}%",
                "capas_teselas": len(state.tile_layers),
                "items_stac": list(state.stac_items_found.keys()),
            }
        )

        return state, trace
