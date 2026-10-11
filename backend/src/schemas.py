from typing import List, Dict, Optional, Any
from pydantic import BaseModel, Field

class AnalyzeRequest(BaseModel):
    lat: float = Field(..., description="Latitud en Provincia de Buenos Aires (ej: -35.57)")
    lon: float = Field(..., description="Longitud en Provincia de Buenos Aires (ej: -58.01)")
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

class GeospatialState(BaseModel):
    parcel_name: str
    lat: float
    lon: float
    bbox: List[float]
    elevation_m: float
    slope_deg: float
    relative_depression_score: float # 0.0 (loma) a 1.0 (cubeta cerrada)
    jrc_occurrence_pct: float # 0 a 100%
    jrc_max_extent: bool # True si alguna vez se inundó en los últimos 35 años
    jrc_seasonality: str # "permanente", "estacional", "efímero" o "seco"
    sar_backscatter_db: float # retrodispersión radar Sentinel-1
    sentinel2_ndwi: float # índice de agua / humedad (-1 a 1)
    stac_items_found: Dict[str, str]
    tile_layers: List[TileLayerInfo]

class HydroRiskProfile(BaseModel):
    riesgo_inundacion_severo_prob: float = Field(..., description="Probabilidad Noul de anegamiento crítico")
    vulnerabilidad_topografica_score: int = Field(..., description="Score 0 a 3 de retención")
    vulnerabilidad_topografica_label: str
    mecanismo_hidrico_dominante: str
    mecanismo_hidrico_label: str
    mecanismo_probabilities: Dict[str, float]
    confidence: float
    resumen_hidrologico: str

class AgroVerdict(BaseModel):
    aptitud_productiva: str
    aptitud_productiva_label: str
    aptitud_probabilities: Dict[str, float]
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
