import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .config import GEMINI_MODEL, HOST, JEV_API_KEY, PORT
from .orchestrator import orchestrator
from .presets import PRESET_LOCATIONS
from .schemas import AnalyzeRequest, MultiAgentAnalysisResult, PresetLocation
from .services.key_rotator import key_rotator, mask_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("terreno_cultivable_backend")

app = FastAPI(
    title="Terreno Cultivable API - Monitor Geoespacial Satelital",
    description="Sistema Multiagente con JEV (TypeSafe System One), Rotador de API Keys y Telemetría Satelital Real (Microsoft Planetary Computer STAC + OSM)",
    version="2.0.0"
)

# CORS para comunicación con el frontend en Astro
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    rotator_status = key_rotator.get_status()
    return {
        "app": "Terreno Cultivable API - Satelital Real",
        "status": "online",
        "docs": "/docs",
        "multiagent": ["GeoExtractorAgent", "HydroRiskAgent", "AgroVerdictAgent"],
        "jev_configured": rotator_status["total_unique_keys"] > 0 or bool(JEV_API_KEY),
        "api_keys_pool_size": rotator_status["total_unique_keys"],
        "gemini_model": GEMINI_MODEL,
    }

@app.get("/api/health")
async def health_check():
    rotator_status = key_rotator.get_status()
    return {
        "status": "healthy",
        "jev_api_key_configured": rotator_status["total_unique_keys"] > 0 or bool(JEV_API_KEY),
        "api_key_prefix": mask_api_key(JEV_API_KEY) if JEV_API_KEY else None,
        "gemini_model": GEMINI_MODEL,
        "key_rotator": rotator_status,
        "coverage": "Global (Planetary Computer STAC + OSM)"
    }

@app.get("/api/keys/status")
async def get_keys_status():
    """Retorna el estado en tiempo real del rotador de API keys cargadas desde .env."""
    return key_rotator.get_status()

@app.get("/api/presets", response_model=list[PresetLocation])
async def get_presets():
    """Retorna ubicaciones preconfiguradas representativas de entornos agrícolas, fluviales, costeros, humedales, serranos y urbanos."""
    return PRESET_LOCATIONS

@app.post("/api/analyze", response_model=MultiAgentAnalysisResult)
async def analyze_parcel(request: AnalyzeRequest):
    """
    Ejecuta el pipeline multiagente con telemetría satelital real para cualquier coordenada WGS84.
    """
    logger.info(f"Petición de análisis recibida: ({request.lat}, {request.lon}) - '{request.parcel_name}'")

    if not (-90.0 <= request.lat <= 90.0 and -180.0 <= request.lon <= 180.0):
        raise HTTPException(status_code=422, detail="Coordenadas WGS84 fuera de rango válido.")

    try:
        result = await orchestrator.run(request)
        return result
    except Exception as e:
        logger.exception("Error durante la ejecución del pipeline multiagente")
        raise HTTPException(status_code=500, detail=f"Error en el análisis multiagente: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=HOST, port=PORT, reload=True)
