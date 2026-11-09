import time
import logging
from typesafe_sdk import Choice, Noul, Score
from ..schemas import GeospatialState, HydroRiskProfile, AgentExecutionTrace
from ..services.jev_service import jev_service

logger = logging.getLogger(__name__)

SCORE_LABELS = {
    0: "Loma alta / Drenaje excelente",
    1: "Plano suave / Drenaje moderado",
    2: "Bajo o cubeta / Drenaje deficiente",
    3: "Depresión crítica / Acumulación severa"
}

MECANISMO_LABELS = {
    "desborde_cuenca": "Desborde fluvial o lagunar de la cuenca",
    "escurrimiento_pluvial_lento": "Estancamiento pluvial por escasa pendiente",
    "afloramiento_napa_freatica": "Afloramiento / saturación de napa freática",
    "sin_anegamiento": "Zona alta protegida de anegamientos"
}

class HydroRiskAgent:
    """
    Agente 2: Evaluación de Riesgo Hidrológico y Geomorfológico.
    Utiliza JEV (TypeSafe System One) para emitir juicios tipados (Noul, Score, Choice)
    calibrados matemáticamente sobre la probabilidad y mecanismo de anegamiento del lote.
    """
    def __init__(self):
        self.name = "HydroRiskAgent (JEV System One)"

    async def execute(self, geo_state: GeospatialState) -> tuple[HydroRiskProfile, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Evaluando riesgo hidrológico con JEV para {geo_state.parcel_name}...")

        geom = geo_state.topography.geomorphology
        zones_summary = {
            z.zone_id: f"{z.percentage}% ({z.area_ha} ha)"
            for z in geo_state.topography.terrain_zones
        }

        # Estructuramos el estado semántico enriquecido con índices topográficos para Jev
        jev_state = {
            "parcela": geo_state.parcel_name,
            "ubicacion": f"Provincia de Buenos Aires (Lat: {geo_state.lat}, Lon: {geo_state.lon})",
            "unidad_geomorfologica": geom.region_geomorphology,
            "red_drenaje": geom.drainage_network_type,
            "cota_elevacion_msnm": geo_state.elevation_m,
            "amplitud_relieve_m": geom.relief_amplitude_m,
            "pendiente_grados": geo_state.slope_deg,
            "pendiente_porcentaje": geom.slope_pct,
            "indice_depresion_relativa_0_a_1": geo_state.relative_depression_score,
            "indice_humedad_topografica_twi": geom.twi_value,
            "indice_posicion_topografica_tpi_m": geom.tpi_value_m,
            "profundidad_napa_freatica_estimada_m": geom.estimated_water_table_depth_m,
            "distribucion_ambientes_lote": zones_summary,
            "recurrencia_historica_agua_jrc_pct": geo_state.jrc_occurrence_pct,
            "estacionalidad_agua": geo_state.jrc_seasonality,
            "retrodispersion_radar_sar_db": geo_state.sar_backscatter_db,
            "indice_humedad_ndwi": geo_state.sentinel2_ndwi,
        }

        # Preguntas tipadas de System One
        questions = {
            "riesgo_severo": Noul(
                instructions=(
                    "Considerando el régimen hidrológico de la Provincia de Buenos Aires, el índice TWI "
                    "(`indice_humedad_topografica_twi`), la profundidad de napa (`profundidad_napa_freatica_estimada_m`) "
                    "y la recurrencia histórica JRC (`recurrencia_historica_agua_jrc_pct`), ¿este lote presenta "
                    "una alta probabilidad de anegamiento crítico o persistente bajo períodos de lluvias copiosas?"
                )
            ),
            "vulnerabilidad_topografica": Score(
                instructions="¿Cuál es el grado de vulnerabilidad topográfica del terreno frente a la acumulación de escorrentía?",
                criteria=[
                    "Loma alta con pendiente óptima y drenaje natural excelente",
                    "Plano suave con escurrimiento moderado a lento",
                    "Bajo suave o cubeta intermedia susceptible a anegamiento temporario",
                    "Depresión crítica, cañada o cubeta cerrada con acumulación severa"
                ]
            ),
            "mecanismo_hidrico": Choice(
                instructions="¿Cuál es el mecanismo hidrológico dominante causante de acumulación de agua en este lote?",
                criteria={
                    "desborde_cuenca": "Desborde de ríos, arroyos o lagunas de la cuenca hídrica",
                    "escurrimiento_pluvial_lento": "Escurrimiento plano lento por pendiente casi nula y lluvias locales",
                    "afloramiento_napa_freatica": "Saturación por napa freática alta muy cercana a la superficie",
                    "sin_anegamiento": "Relieve alto sin riesgo significativo de anegamiento"
                }
            )
        }

        response = await jev_service.evaluate_system_one(jev_state, questions)

        # Extracción tipada
        noul_val = round(response.nouls["riesgo_severo"].noul, 3)
        
        score_obj = response.scores["vulnerabilidad_topografica"]
        score_val = int(round(score_obj.score))
        score_val = max(0, min(3, score_val))
        score_label = SCORE_LABELS.get(score_val, "Moderado")

        choice_obj = response.choices["mecanismo_hidrico"]
        choice_key = str(choice_obj.choice)
        choice_label = MECANISMO_LABELS.get(choice_key, choice_key)
        choice_probs = {k: round(v, 3) for k, v in choice_obj.probabilities.items()}

        confidence = round(float(choice_obj.confidence or 0.9), 3)

        # Resumen hidrológico
        if noul_val > 0.65:
            resumen = f"Riesgo hídrico crítico ({int(noul_val*100)}%). Sujeto a {choice_label.lower()} con drenaje deficiente (TWI {geom.twi_value})."
        elif noul_val > 0.35:
            resumen = f"Riesgo hídrico moderado/intermedio ({int(noul_val*100)}%). Vulnerabilidad en eventos Niño (Napa est. {geom.estimated_water_table_depth_m}m)."
        else:
            resumen = f"Riesgo hídrico bajo ({int(noul_val*100)}%). Buena posición topográfica y drenaje favorable (Pendiente {geom.slope_pct}%)."

        profile = HydroRiskProfile(
            riesgo_inundacion_severo_prob=noul_val,
            vulnerabilidad_topografica_score=score_val,
            vulnerabilidad_topografica_label=score_label,
            mecanismo_hidrico_dominante=choice_key,
            mecanismo_hidrico_label=choice_label,
            mecanismo_probabilities=choice_probs,
            confidence=confidence,
            resumen_hidrologico=resumen
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace = AgentExecutionTrace(
            agent_id="agent_2_hydro_risk",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "prob_inundacion": f"{int(profile.riesgo_inundacion_severo_prob * 100)}%",
                "topografia": profile.vulnerabilidad_topografica_label,
                "mecanismo": profile.mecanismo_hidrico_label,
                "jev_confidence": f"{int(profile.confidence * 100)}%",
            }
        )

        return profile, trace
