import time
import logging
from typing import List
from typesafe_sdk import Choice, Noul, Score
from ..schemas import GeospatialState, HydroRiskProfile, AgroVerdict, AgentExecutionTrace
from ..services.jev_service import jev_service

logger = logging.getLogger(__name__)

APTITUD_LABELS = {
    "agricola_plena": "Apto Agricultura Continua (Alta Productividad)",
    "mixto_agricola_ganadero": "Apto Mixto Agrícola-Ganadero (Rotación Forrajera)",
    "ganadero_pastizal_bajos": "Apto Ganadería de Cría (Pastizal Natural de Bajos)",
    "no_agricola_humedal": "No Cultivable (Cuerpo de Agua / Reserva Hídrica)"
}

RESILIENCIA_LABELS = {
    0: "Muy vulnerable a excesos hídricos (Ciclos El Niño)",
    1: "Resiliencia media (Manejable con fechas de siembra)",
    2: "Alta resiliencia y estabilidad interanual"
}

class AgroVerdictAgent:
    """
    Agente 3: Clasificación y Dictamen Agronómico.
    Sintetiza la firma geoespacial y la evaluación de riesgo hidrológico,
    utilizando JEV para clasificar la aptitud del suelo, resiliencia climática
    y emitir recomendaciones agronómicas y cultivos viables.
    """
    def __init__(self):
        self.name = "AgroVerdictAgent (JEV System One)"

    async def execute(
        self,
        geo_state: GeospatialState,
        hydro_profile: HydroRiskProfile
    ) -> tuple[AgroVerdict, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Emitiendo dictamen agronómico con JEV para {geo_state.parcel_name}...")

        # Estado semántico cruzado para Jev
        synthesized_state = {
            "parcela": geo_state.parcel_name,
            "ubicacion_pba": f"Lat: {geo_state.lat}, Lon: {geo_state.lon}",
            "cota_msnm": geo_state.elevation_m,
            "pendiente_grados": geo_state.slope_deg,
            "recurrencia_historica_agua_pct": geo_state.jrc_occurrence_pct,
            "probabilidad_inundacion_severa": hydro_profile.riesgo_inundacion_severo_prob,
            "posicion_topografica": hydro_profile.vulnerabilidad_topografica_label,
            "mecanismo_hidrico": hydro_profile.mecanismo_hidrico_label,
        }

        questions = {
            "aptitud": Choice(
                instructions=(
                    "Evaluando las condiciones edáficas e hidrológicas en la Provincia de Buenos Aires, "
                    "¿cuál es la aptitud de uso agropecuario más viable y sustentable para este lote?"
                ),
                criteria={
                    "agricola_plena": "Apto agricultura continua (soja, maíz, trigo/cebada, girasol)",
                    "mixto_agricola_ganadero": "Apto rotación agrícola-ganadera con pasturas consociadas",
                    "ganadero_pastizal_bajos": "Apto ganadería de cría sobre pastizales naturales o promocionados",
                    "no_agricola_humedal": "Inapto para laboreo agrícola / espejo de agua o bajo permanente"
                }
            ),
            "resiliencia": Score(
                instructions="¿Qué nivel de resiliencia y estabilidad productiva tiene el campo frente a la alternancia Niño/Niña?",
                criteria=[
                    "Muy vulnerable con alto riesgo de pérdida de cosecha en años húmedos",
                    "Resiliencia media manejable mediante ajuste de ciclos y drenaje superficial",
                    "Alta resiliencia con excelente estabilidad productiva interanual"
                ]
            ),
            "requiere_obras": Noul(
                instructions="¿Requiere el lote inversiones en obras de drenaje, zanjeo de alivio, canales o curvas de nivel para cultivar de forma segura?"
            )
        }

        response = await jev_service.evaluate_system_one(synthesized_state, questions)

        # Extracción tipada
        choice_obj = response.choices["aptitud"]
        aptitud_key = str(choice_obj.choice)
        aptitud_label = APTITUD_LABELS.get(aptitud_key, aptitud_key)
        aptitud_probs = {k: round(v, 3) for k, v in choice_obj.probabilities.items()}

        resiliencia_val = int(round(response.scores["resiliencia"].score))
        resiliencia_val = max(0, min(2, resiliencia_val))
        resiliencia_label = RESILIENCIA_LABELS.get(resiliencia_val, "Moderada")

        requiere_obras_prob = round(response.nouls["requiere_obras"].noul, 3)
        requiere_obras = requiere_obras_prob >= 0.5

        # Cálculo del Score de Aptitud Agrícola (0 - 100)
        # Basado en la probabilidad de agricultura, penalizaciones por riesgo de inundación y resiliencia
        base_score = 95 if aptitud_key == "agricola_plena" else (
            68 if aptitud_key == "mixto_agricola_ganadero" else (
                38 if aptitud_key == "ganadero_pastizal_bajos" else 10
            )
        )
        penalty_risk = int(hydro_profile.riesgo_inundacion_severo_prob * 30)
        resilience_bonus = resiliencia_val * 8
        final_score = max(5, min(98, base_score - penalty_risk + resilience_bonus))

        # Semáforo
        if final_score >= 75:
            color = "verde"
        elif final_score >= 45:
            color = "amarillo"
        else:
            color = "rojo"

        # Recomendaciones y cultivos según aptitud
        recomendaciones: List[str] = []
        cultivos: List[str] = []

        if aptitud_key == "agricola_plena":
            dictamen = (
                f"Lote con excelente potencial agronómico ({final_score}/100). "
                f"Topografía favorable con drenaje natural eficiente y mínimo riesgo de anegamiento."
            )
            cultivos = ["Soja de 1ª", "Maíz temprano", "Trigo / Soja 2ª", "Cebada cervecera", "Girasol"]
            recomendaciones = [
                "Mantener esquema de siembra directa con cobertura permanente de rastrojo.",
                "Rotación equitativa gramíneas/oleaginosas para conservar estructura edáfica.",
                "Monitorear balance de nutrientes (Fósforo y Nitrógeno) en presiembra."
            ]
        elif aptitud_key == "mixto_agricola_ganadero":
            dictamen = (
                f"Lote de aptitud mixta ({final_score}/100). "
                f"Apto para agricultura en lomas y rotación con pasturas perennes en medias lomas."
            )
            cultivos = ["Maíz tardío", "Sorgo granífero/forrajero", "Pasturas de Alfalfa / Festuca", "Avena / Vicia"]
            recomendaciones = [
                "Implementar rotaciones con pasturas perennes para mejorar infiltración.",
                "Priorizar cultivos con tolerancia a períodos cortos de saturación (Sorgo, Maíz tardío).",
                "Trazar curvas de nivel y pequeños zanjeos de drenaje hacia bajos naturales."
            ]
        elif aptitud_key == "ganadero_pastizal_bajos":
            dictamen = (
                f"Lote clasificado como no apto para agricultura regular ({final_score}/100). "
                f"Destino óptimo: ganadería de cría y recría sobre pastizal de bajo."
            )
            cultivos = ["Lotus tenuis / corniculatus", "Agropiro alargado", "Festuca arundinacea", "Raygrass anual"]
            recomendaciones = [
                "Evitar laboreo convencional para no degradar el horizonte superficial ni salinizar.",
                "Promover siembra de Lotus tenuis y Agropiro por su alta tolerancia a salinidad y anegamiento.",
                "Ajustar carga animal durante el invierno y primavera en función del nivel freático."
            ]
        else:
            dictamen = (
                f"Lote con limitación hídrica severa ({final_score}/100). "
                f"Comportamiento de cubeta o humedal permanente. Restricción absoluta para laboreo."
            )
            cultivos = ["Vegetación hidrófila natural"]
            recomendaciones = [
                "Preservar como zona de retención hídrica natural y refugio de biodiversidad.",
                "No realizar movimientos de suelo que alteren el drenaje regional de la cuenca."
            ]

        if requiere_obras:
            recomendaciones.append(
                f"Se recomienda evaluar obras de zanjeo o canalización menor (probabilidad de necesidad: {int(requiere_obras_prob*100)}%)."
            )

        verdict = AgroVerdict(
            aptitud_productiva=aptitud_key,
            aptitud_productiva_label=aptitud_label,
            aptitud_probabilities=aptitud_probs,
            resiliencia_climatica_score=resiliencia_val,
            resiliencia_climatica_label=resiliencia_label,
            requiere_obras_drenaje=requiere_obras,
            requiere_obras_prob=requiere_obras_prob,
            score_aptitud_agricola=final_score,
            color_semaforo=color,
            dictamen_ejecutivo=dictamen,
            recomendaciones_agronomicas=recomendaciones,
            cultivos_sugeridos=cultivos
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace = AgentExecutionTrace(
            agent_id="agent_3_agro_verdict",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "aptitud": verdict.aptitud_productiva_label,
                "score_agricola": f"{verdict.score_aptitud_agricola}/100",
                "semaforo": verdict.color_semaforo.upper(),
                "resiliencia": verdict.resiliencia_climatica_label,
            }
        )

        return verdict, trace
