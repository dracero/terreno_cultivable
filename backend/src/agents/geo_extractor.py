import time
import logging
from ..schemas import AnalyzeRequest, GeospatialState, AgentExecutionTrace
from ..services.planetary_stac import query_planetary_stac
from ..services.topography_engine import build_topographic_analysis

logger = logging.getLogger(__name__)

class GeoExtractorAgent:
    """
    Agente 1: Ingesta Geoespacial, Modelado Topográfico y Geomorfológico.
    Consulta la API STAC de Microsoft Planetary Computer (JRC Global Surface Water,
    Copernicus DEM, Sentinel-1 y Sentinel-2) y genera la malla DEM local, curvas de nivel,
    vectores de escurrimiento D8, perfiles de corte e índices geomorfológicos (TWI, TPI, LS).
    """
    def __init__(self):
        self.name = "GeoExtractorAgent (STAC + Topografía DEM)"

    async def execute(self, request: AnalyzeRequest) -> tuple[GeospatialState, AgentExecutionTrace]:
        start_time = time.perf_counter()
        area_ha = request.area_ha or 100.0
        logger.info(f"[{self.name}] Consultando STAC y modelando topografía para ({request.lat}, {request.lon})...")

        stac_data = await query_planetary_stac(request.lat, request.lon)

        topo_data = build_topographic_analysis(
            lat=request.lat,
            lon=request.lon,
            elevation_m=stac_data["elevation_m"],
            slope_deg=stac_data["slope_deg"],
            depression_score=stac_data["relative_depression_score"],
            area_ha=area_ha,
        )

        state = GeospatialState(
            parcel_name=request.parcel_name or "Parcela Rural",
            lat=request.lat,
            lon=request.lon,
            area_ha=area_ha,
            bbox=stac_data["bbox"],
            elevation_m=stac_data["elevation_m"],
            slope_deg=stac_data["slope_deg"],
            slope_pct=topo_data.geomorphology.slope_pct,
            relative_depression_score=stac_data["relative_depression_score"],
            jrc_occurrence_pct=stac_data["jrc_occurrence_pct"],
            jrc_max_extent=stac_data["jrc_max_extent"],
            jrc_seasonality=stac_data["jrc_seasonality"],
            sar_backscatter_db=stac_data["sar_backscatter_db"],
            sentinel2_ndwi=stac_data["sentinel2_ndwi"],
            stac_items_found=stac_data["stac_items_found"],
            tile_layers=stac_data["tile_layers"],
            topography=topo_data,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace = AgentExecutionTrace(
            agent_id="agent_1_geo_extractor",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "cota_msnm": f"{state.elevation_m} m (Δ {topo_data.geomorphology.relief_amplitude_m} m)",
                "pendiente": f"{state.slope_deg}° ({state.slope_pct}%)",
                "twi_humedad": f"{topo_data.geomorphology.twi_value}",
                "curvas_nivel": len(topo_data.contours),
                "jrc_agua_pct": f"{state.jrc_occurrence_pct}%",
            }
        )

        return state, trace
