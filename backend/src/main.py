import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from .config import JEV_API_KEY, PORT, HOST
from .schemas import AnalyzeRequest, MultiAgentAnalysisResult, PresetLocation
from .presets import PRESET_LOCATIONS
from .orchestrator import orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("terreno_cultivable_backend")

app = FastAPI(
    title="Terreno Cultivable API - Buenos Aires",
    description="Sistema Multiagente con JEV (TypeSafe System One) y Microsoft Planetary Computer STAC",
    version="1.0.0"
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
    return {
        "app": "Terreno Cultivable API - PBA",
        "status": "online",
        "docs": "/docs",
        "multiagent": ["GeoExtractorAgent", "HydroRiskAgent", "AgroVerdictAgent"],
        "jev_configured": bool(JEV_API_KEY)
    }

@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "jev_api_key_configured": bool(JEV_API_KEY),
        "api_key_prefix": JEV_API_KEY[:10] + "..." if JEV_API_KEY else None,
        "region": "Provincia de Buenos Aires, Argentina"
    }

@app.get("/api/presets", response_model=list[PresetLocation])
async def get_presets():
    """Retorna ubicaciones preconfiguradas con diferentes tipologías hídricas de Bs. As."""
    return PRESET_LOCATIONS

@app.post("/api/analyze", response_model=MultiAgentAnalysisResult)
async def analyze_parcel(request: AnalyzeRequest):
    """
    Ejecuta el pipeline multiagente para analizar una coordenada o lote en la Provincia de Buenos Aires.
    """
    logger.info(f"Petición de análisis recibida: ({request.lat}, {request.lon}) - '{request.parcel_name}'")
    
    # Validar que las coordenadas estén dentro del cono sur / Buenos Aires aproximadamente
    # Latitud PBA: entre -41.2 y -33.0 aprox
    # Longitud PBA: entre -63.5 y -56.5 aprox
    if not (-42.0 <= request.lat <= -32.5 and -64.0 <= request.lon <= -56.0):
        logger.warning(f"Coordenadas fuera de la región habitual de Bs. As.: ({request.lat}, {request.lon})")
        # No bloqueamos pero avisamos en logs para permitir pruebas amplias

    try:
        result = await orchestrator.run(request)
        return result
    except Exception as e:
        logger.exception("Error durante la ejecución del pipeline multiagente")
        raise HTTPException(status_code=500, detail=f"Error en el análisis multiagente: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host=HOST, port=PORT, reload=True)
