import math
import time
import logging
from ..schemas import AnalyzeRequest, GeospatialState, AgentExecutionTrace
from ..services.planetary_stac import query_planetary_stac
from ..services.topography_engine import build_topographic_analysis

logger = logging.getLogger(__name__)


class GeoExtractorAgent:
    """
    Agente 1: Ingesta Geoespacial, Teledetección Real y Modelado Topográfico.
    Consulta en paralelo la API STAC/Data de Microsoft Planetary Computer (Copernicus DEM 30m,
    JRC Global Surface Water, ESA WorldCover 10m, Sentinel-2 L2A, Sentinel-1 RTC) y Nominatim
    OSM; calcula derivadas reales del DEM, detección hidrológica/costera y zonificación.
    """

    def __init__(self):
        self.name = "GeoExtractorAgent (STAC Real + DEM + WorldCover)"

    async def execute(self, request: AnalyzeRequest) -> tuple[GeospatialState, AgentExecutionTrace]:
        start_time = time.perf_counter()
        area_ha = request.area_ha or 100.0
        logger.info(f"[{self.name}] Consultando STAC real y modelando DEM para ({request.lat}, {request.lon})...")

        stac_data = await query_planetary_stac(request.lat, request.lon, area_ha=area_ha)
        topo_data = build_topographic_analysis(
            lat=request.lat,
            lon=request.lon,
            stac_data=stac_data,
            area_ha=area_ha,
        )

        slope_pct = topo_data.geomorphology.slope_pct
        slope_deg = round(math.degrees(math.atan(slope_pct / 100.0)), 2)
        hydro_env = stac_data.get("hydro_env") or {}
        loc_label = str(stac_data.get("location_label", "Ubicación Satelital"))

        state = GeospatialState(
            parcel_name=request.parcel_name or loc_label,
            lat=request.lat,
            lon=request.lon,
            area_ha=area_ha,
            bbox=stac_data["bbox"],
            location_label=loc_label,
            environment_type=str(hydro_env.get("environment_type", "rural_agricola")),
            environment_label=str(hydro_env.get("environment_label", "Terreno Rural")),
            water_body_type=str(hydro_env.get("water_body_type", "ninguno")),
            water_distance_m=hydro_env.get("water_distance_m"),
            coast_detected=bool(hydro_env.get("coast_detected", False)),
            river_detected=bool(hydro_env.get("river_detected", False)),
            urban_detected=bool(hydro_env.get("urban_detected", False)),
            elevation_m=stac_data["elevation_m"],
            slope_deg=slope_deg,
            slope_pct=slope_pct,
            relative_depression_score=stac_data["relative_depression_score"],
            jrc_occurrence_pct=stac_data["jrc_occurrence_pct"],
            jrc_max_extent=stac_data["jrc_max_extent"],
            jrc_seasonality=stac_data["jrc_seasonality"],
            sar_backscatter_db=stac_data["sar_backscatter_db"],
            sentinel2_ndwi=stac_data["sentinel2_ndwi"],
            sentinel2_mndwi=float(stac_data.get("sentinel2_mndwi", 0.0)),
            sentinel2_ndvi=float(stac_data.get("sentinel2_ndvi", 0.0)),
            satellite_scene_date=stac_data.get("satellite_scene_date"),
            land_cover_breakdown=stac_data.get("land_cover_breakdown") or {},
            water_mask_grid=hydro_env.get("water_mask_grid") or [],
            data_source_mode=str(stac_data.get("data_source_mode", "planetary_computer_real")),
            stac_items_found=stac_data["stac_items_found"],
            tile_layers=stac_data["tile_layers"],
            topography=topo_data,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        dist_txt = (
            f" (agua a {state.water_distance_m:.0f} m)"
            if state.water_distance_m is not None
            else ""
        )
        trace = AgentExecutionTrace(
            agent_id="agent_1_geo_extractor",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "ubicacion": loc_label,
                "entorno_detectado": f"{state.environment_label}{dist_txt}",
                "cota_msnm": f"{state.elevation_m} m (Δ {topo_data.geomorphology.relief_amplitude_m} m)",
                "pendiente": f"{state.slope_deg}° ({state.slope_pct}%)",
                "espectro_s2": f"NDVI {state.sentinel2_ndvi:+.2f} / MNDWI {state.sentinel2_mndwi:+.2f}",
                "jrc_agua_pct": f"{state.jrc_occurrence_pct}% ({state.jrc_seasonality})",
            },
        )

        return state, trace
