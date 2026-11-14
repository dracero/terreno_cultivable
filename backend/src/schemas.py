from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    lat: float = Field(..., description="Latitud en grados decimales (ej: -35.57)")
    lon: float = Field(..., description="Longitud en grados decimales (ej: -58.01)")
    parcel_name: Optional[str] = Field(default="Parcela Rural", description="Nombre o identificación del lote")
    area_ha: Optional[float] = Field(default=100.0, description="Superficie aproximada en hectáreas")

class PresetLocation(BaseModel):
    id: str
    name: str
    partido: str
    lat: float
    lon: float
    description: str
    badge: str
    typology: str

class TileLayerInfo(BaseModel):
    name: str
    collection: str
    title: str
    tile_url: str
    attribution: str
    colormap: Optional[str] = None

class ContourLine(BaseModel):
    elevation_m: float = Field(..., description="Cota de la curva de nivel en msnm")
    is_major: bool = Field(default=False, description="Indica si es curva maestra o principal")
    polylines: List[List[List[float]]] = Field(..., description="Lista de polilíneas [[lat, lon], ...]")

class FlowVector(BaseModel):
    lat: float
    lon: float
    target_lat: float
    target_lon: float
    azimuth_deg: float
    slope_pct: float
    flow_accumulation: int
    is_drainage_channel: bool = False

class ProfilePoint(BaseModel):
    distance_m: float
    lat: float
    lon: float
    elevation_m: float
    water_table_msnm: float
    water_table_depth_m: float
    slope_local_pct: float
    zone_id: str

class ElevationProfile(BaseModel):
    profile_id: str
    title: str
    total_distance_m: float
    min_elevation_m: float
    max_elevation_m: float
    relief_delta_m: float
    avg_slope_pct: float
    max_slope_pct: float
    points: List[ProfilePoint]

class TerrainZoneStat(BaseModel):
    zone_id: str
    zone_name: str
    percentage: float
    area_ha: float
    mean_elevation_m: float
    color_hex: str
    agronomic_use: str

class GeomorphologyMetrics(BaseModel):
    region_geomorphology: str
    soil_taxonomy_inta: str
    drainage_network_type: str
    slope_pct: float
    max_slope_pct: float
    min_elevation_m: float
    max_elevation_m: float
    relief_amplitude_m: float
    contour_interval_m: float
    twi_value: float
    twi_label: str
    tpi_value_m: float
    tpi_label: str
    tri_rugosity_m: float
    aspect_deg: float
    aspect_cardinal: str
    ls_erosion_factor: float
    erosion_risk_label: str
    estimated_water_table_depth_m: float

class TopographicAnalysisData(BaseModel):
    grid_lats: List[float]
    grid_lons: List[float]
    elevation_grid: List[List[float]]
    zone_grid: List[List[str]]
    water_table_base_msnm: float
    geomorphology: GeomorphologyMetrics
    terrain_zones: List[TerrainZoneStat]
    contours: List[ContourLine]
    flow_vectors: List[FlowVector]
    elevation_profiles: List[ElevationProfile]
    geodesy: Dict[str, Any] = Field(default_factory=dict, description="Ficha técnica geodésica oficial (POSGAR 2007, Gauss-Krüger, Geoide, UTM)")

class GeospatialState(BaseModel):
    parcel_name: str
    lat: float
    lon: float
    area_ha: float = 100.0
    bbox: List[float]
    location_label: str = "Ubicación Satelital"
    environment_type: str = "rural_agricola"
    environment_label: str = "Terreno Rural"
    water_body_type: str = "ninguno"
    water_distance_m: Optional[float] = None
    coast_detected: bool = False
    river_detected: bool = False
    urban_detected: bool = False
    elevation_m: float
    slope_deg: float
    slope_pct: float = 0.1
    relative_depression_score: float  # 0.0 (alto/bien drenado) a 1.0 (depresión inundable/agua)
    jrc_occurrence_pct: float  # 0 a 100%
    jrc_max_extent: bool  # True si alguna vez tuvo agua en JRC 35+ años
    jrc_seasonality: str  # "permanente", "estacional", "efímero", "seco" o "mar abierto"
    sar_backscatter_db: float  # retrodispersión radar Sentinel-1 en dB
    sentinel2_ndwi: float  # índice de agua / humedad (-1 a 1)
    sentinel2_mndwi: float = 0.0  # índice modificado de agua (B03-B11)/(B03+B11)
    sentinel2_ndvi: float = 0.0  # índice de vegetación (B08-B04)/(B08+B04)
    satellite_scene_date: Optional[str] = None
    land_cover_breakdown: Dict[str, float] = Field(default_factory=dict)
    water_mask_grid: List[List[int]] = Field(default_factory=list)
    data_source_mode: str = "planetary_computer_real"
    stac_items_found: Dict[str, str]
    tile_layers: List[TileLayerInfo]
    topography: TopographicAnalysisData

class HydroRiskProfile(BaseModel):
    riesgo_inundacion_severo_prob: float = Field(..., description="Probabilidad Noul de anegamiento crítico")
    vulnerabilidad_topografica_score: int = Field(..., description="Score 0 a 3 de retención")
    vulnerabilidad_topografica_label: str
    mecanismo_hidrico_dominante: str
    mecanismo_hidrico_label: str
    mecanismo_probabilities: Dict[str, float]
    confidence: float
    resumen_hidrologico: str
    hidrografia_detectada: str = "Sin cursos ni espejos superficiales cercanos"

class AgroVerdict(BaseModel):
    aptitud_productiva: str
    aptitud_productiva_label: str
    aptitud_probabilities: Dict[str, float]
    clase_capacidad_uso_inta: str = "clase_I_II"
    clase_capacidad_uso_label: str = "Clase I-II (Agrícola sin limitaciones severas)"
    limitante_edafica_codigo: str = "sin_limitante"
    limitante_edafica_label: str = "Sin limitantes críticas"
    indice_productividad_ip: int = 75
    manejo_por_ambientes_recomendado: bool = True
    manejo_por_ambientes_prob: float = 0.65
    resiliencia_climatica_score: int # 0 a 2
    resiliencia_climatica_label: str
    requiere_obras_drenaje: bool
    requiere_obras_prob: float
    score_aptitud_agricola: int # 0 a 100
    color_semaforo: str # "verde", "amarillo", "rojo"
    dictamen_ejecutivo: str
    recomendaciones_agronomicas: List[str]
    cultivos_sugeridos: List[str]

class AgentExecutionTrace(BaseModel):
    agent_id: str
    agent_name: str
    status: str
    duration_ms: float
    highlights: Dict[str, Any]

class MultiAgentAnalysisResult(BaseModel):
    request: AnalyzeRequest
    geospatial: GeospatialState
    hydro_risk: HydroRiskProfile
    verdict: AgroVerdict
    traces: List[AgentExecutionTrace]
    execution_time_total_ms: float
