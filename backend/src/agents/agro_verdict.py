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

CLASE_INTA_LABELS = {
    "clase_I_II": "Clases I – II (Agrícola sin limitaciones severas)",
    "clase_III_IV": "Clases III – IV (Agrícola condicional / Rotación)",
    "clase_V_VI": "Clases V – VI (Ganadero / Pasturas permanentes)",
    "clase_VII_VIII": "Clases VII – VIII (Reserva hídrica / Sin uso arable)"
}

LIMITANTE_LABELS = {
    "sin_limitante": "Subclase 0 · Sin limitantes críticas",
    "exceso_hidrico_w": "Subclase w · Exceso hídrico y drenaje impedido",
    "erosion_escorrentia_e": "Subclase e · Susceptibilidad a erosión por pendiente",
    "salinidad_alcalinidad_s": "Subclase s · Alcalinidad sódica (Bt nátrico) / Suelo somero"
}

RESILIENCIA_LABELS = {
    0: "Muy vulnerable a excesos hídricos (Ciclos El Niño)",
    1: "Resiliencia media (Manejable con fechas de siembra)",
    2: "Alta resiliencia y estabilidad interanual"
}

class AgroVerdictAgent:
    """
    Agente 3: Clasificación Edáfica, Capacidad de Uso INTA y Dictamen Agronómico.
    Sintetiza la firma geoespacial, los índices topográficos (TWI, TPI, LS) y la evaluación
    de riesgo hidrológico utilizando JEV para clasificar la aptitud del suelo, la Clase de
    Capacidad de Uso (I-VIII), la Subclase limitante (w, e, s) y el manejo por ambientes.
    """
    def __init__(self):
        self.name = "AgroVerdictAgent (JEV System One)"

    async def execute(
        self,
        geo_state: GeospatialState,
        hydro_profile: HydroRiskProfile
    ) -> tuple[AgroVerdict, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Emitiendo dictamen agronómico y edáfico con JEV para {geo_state.parcel_name}...")

        geom = geo_state.topography.geomorphology
        zones_pct = {z.zone_id: z.percentage for z in geo_state.topography.terrain_zones}

        # Estado semántico cruzado para Jev
        synthesized_state = {
            "parcela": geo_state.parcel_name,
            "ubicacion_pba": f"Lat: {geo_state.lat}, Lon: {geo_state.lon}",
            "region_geomorfologica": geom.region_geomorphology,
            "taxonomia_suelo_estimada": geom.soil_taxonomy_inta,
            "cota_msnm": geo_state.elevation_m,
            "amplitud_relieve_m": geom.relief_amplitude_m,
            "pendiente_grados": geo_state.slope_deg,
            "pendiente_porcentaje": geom.slope_pct,
            "factor_erosion_usle_ls": geom.ls_erosion_factor,
            "indice_humedad_topografica_twi": geom.twi_value,
            "profundidad_napa_m": geom.estimated_water_table_depth_m,
            "zonificacion_ambientes_pct": zones_pct,
            "recurrencia_historica_agua_pct": geo_state.jrc_occurrence_pct,
            "probabilidad_inundacion_severa": hydro_profile.riesgo_inundacion_severo_prob,
            "posicion_topografica": hydro_profile.vulnerabilidad_topografica_label,
            "mecanismo_hidrico": hydro_profile.mecanismo_hidrico_label,
        }

        questions = {
            "aptitud": Choice(
                instructions=(
                    "Evaluando las condiciones edáficas, topográficas e hidrológicas en la Provincia de Buenos Aires, "
                    "¿cuál es la aptitud de uso agropecuario más viable y sustentable para este lote?"
                ),
                criteria={
                    "agricola_plena": "Apto agricultura continua (soja, maíz, trigo/cebada, girasol)",
                    "mixto_agricola_ganadero": "Apto rotación agrícola-ganadera con pasturas consociadas",
                    "ganadero_pastizal_bajos": "Apto ganadería de cría sobre pastizales naturales o promocionados",
                    "no_agricola_humedal": "Inapto para laboreo agrícola / espejo de agua o bajo permanente"
                }
            ),
            "clase_inta": Choice(
                instructions=(
                    "Según el sistema de Clasificación de Capacidad de Uso de la Tierra del INTA / USDA, "
                    "¿en qué grupo de Clases (I a VIII) se ubica predominantemente esta parcela?"
                ),
                criteria={
                    "clase_I_II": "Clases I y II: Tierras arables excelentes con suelos profundos, bien drenados y sin limitaciones severas",
                    "clase_III_IV": "Clases III y IV: Tierras arables con limitaciones moderadas a fuertes (drenaje lento, riesgo de erosión o sequía estacional) que exigen prácticas conservacionistas",
                    "clase_V_VI": "Clases V y VI: Tierras no arables o marginales por anegamiento frecuente, alcalinidad sódica en bajos o pendiente; aptas para pasturas y ganadería",
                    "clase_VII_VIII": "Clases VII y VIII: Humedales permanentes, lagunas, cubetas severas o afloramientos rocosos sin aptitud agropecuaria convencional"
                }
            ),
            "limitante_edafica": Choice(
                instructions=(
                    "¿Cuál es la subclase o factor limitante principal del terreno según la nomenclatura edáfica INTA?"
                ),
                criteria={
                    "sin_limitante": "Sin limitaciones edáficas ni topográficas relevantes (suelo profundo y equilibrado)",
                    "exceso_hidrico_w": "Limitación por exceso de agua (w): drenaje impedido, encharcamiento o napa freática alta",
                    "erosion_escorrentia_e": "Limitación por erosión (e): pendiente pronunciada con riesgo de escorrentía y pérdida de suelo superficial",
                    "salinidad_alcalinidad_s": "Limitación en la zona radicular (s): alcalinidad sódica (horizonte Bt nátrico), baja retención o tosca somera"
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
                instructions="¿Requiere el lote inversiones en obras de drenaje, zanjeo de alivio, canales o curvas de nivel para producir de forma segura?"
            ),
            "manejo_ambientes": Noul(
                instructions=(
                    "Observando la distribución de ambientes (`zonificacion_ambientes_pct`) y la amplitud de relieve (`amplitud_relieve_m`), "
                    "¿es recomendable aplicar Agricultura de Precisión / Manejo por Ambientes diferenciando dosis e insumos entre Loma, Media Loma y Bajo?"
                )
            )
        }

        response = await jev_service.evaluate_system_one(synthesized_state, questions)

        # Extracción tipada
        choice_obj = response.choices["aptitud"]
        aptitud_key = str(choice_obj.choice)
        aptitud_label = APTITUD_LABELS.get(aptitud_key, aptitud_key)
        aptitud_probs = {k: round(v, 3) for k, v in choice_obj.probabilities.items()}

        clase_key = str(response.choices["clase_inta"].choice)
        clase_label = CLASE_INTA_LABELS.get(clase_key, clase_key)

        limitante_key = str(response.choices["limitante_edafica"].choice)
        limitante_label = LIMITANTE_LABELS.get(limitante_key, limitante_key)

        resiliencia_val = int(round(response.scores["resiliencia"].score))
        resiliencia_val = max(0, min(2, resiliencia_val))
        resiliencia_label = RESILIENCIA_LABELS.get(resiliencia_val, "Moderada")

        requiere_obras_prob = round(response.nouls["requiere_obras"].noul, 3)
        requiere_obras = requiere_obras_prob >= 0.5

        manejo_amb_prob = round(response.nouls["manejo_ambientes"].noul, 3)
        manejo_amb = manejo_amb_prob >= 0.45

        # Cálculo del Score de Aptitud Agrícola (0 - 100)
        base_score = 95 if aptitud_key == "agricola_plena" else (
            68 if aptitud_key == "mixto_agricola_ganadero" else (
                38 if aptitud_key == "ganadero_pastizal_bajos" else 10
            )
        )
        penalty_risk = int(hydro_profile.riesgo_inundacion_severo_prob * 30)
        resilience_bonus = resiliencia_val * 8
        final_score = max(5, min(98, base_score - penalty_risk + resilience_bonus))

        # Índice Cartográfico de Productividad INTA estimado (IP 0-100)
        loma_media_pct = zones_pct.get("loma_alta", 25.0) + zones_pct.get("media_loma", 25.0)
        ip_inta = int(round(max(4.0, min(96.0, final_score * 0.72 + loma_media_pct * 0.28))))

        # Semáforo
        if final_score >= 75:
            color = "verde"
        elif final_score >= 45:
            color = "amarillo"
        else:
            color = "rojo"

        # Recomendaciones y cultivos según aptitud y topografía
        recomendaciones: List[str] = []
        cultivos: List[str] = []

        if aptitud_key == "agricola_plena":
            dictamen = (
                f"Lote de alto potencial agronómico ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Predominio de {clase_label} con { round(loma_media_pct, 1) }% de superficie en Loma y Media Loma bien drenadas."
            )
            cultivos = ["Soja de 1ª", "Maíz temprano", "Trigo / Soja 2ª", "Cebada cervecera", "Girasol"]
            recomendaciones = [
                "Mantener esquema de siembra directa con cobertura permanente de rastrojo.",
                "Rotación equitativa gramíneas/oleaginosas para conservar macroporosidad e infiltración.",
                "Ajustar densidad de siembra y nitrógeno por ambiente (mayor potencial en Media Loma húmeda)."
            ]
        elif aptitud_key == "mixto_agricola_ganadero":
            dictamen = (
                f"Lote de aptitud mixta ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Clasificado en {clase_label}. Permite agricultura en lomas ({zones_pct.get('loma_alta', 0)}%) y pasturas en bajos tendidos."
            )
            cultivos = ["Maíz tardío", "Sorgo granífero/forrajero", "Pasturas de Alfalfa / Festuca", "Avena / Vicia"]
            recomendaciones = [
                "Zonificar el lote separando el manejo de Lomas (agrícola) de los Bajos Dulces (forrajero).",
                "Priorizar cultivos con tolerancia a períodos cortos de saturación (Sorgo, Maíz tardío).",
                "Evitar tránsito de maquinaria pesada en bajos cuando el perfil supere capacidad de campo."
            ]
        elif aptitud_key == "ganadero_pastizal_bajos":
            dictamen = (
                f"Lote con restricción para agricultura anual ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Corresponde a {clase_label} ({limitante_label}). Óptimo para ganadería sobre pasturas adaptadas."
            )
            cultivos = ["Lotus tenuis / corniculatus", "Agropiro alargado", "Festuca arundinacea", "Melilotus alba"]
            recomendaciones = [
                "Evitar laboreo convencional para no degradar el horizonte superficial ni ascender sales.",
                "Implantar Agropiro alargado y Lotus tenuis en los bajos alcalinos/hidromórficos.",
                "Planificar apotreramiento respetando las curvas de nivel para separar lomas de reserva forrajera."
            ]
        else:
            dictamen = (
                f"Lote con limitación hídrica severa ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Comportamiento de cubeta receptora ({clase_label}). Restricción absoluta para laboreo agrícola."
            )
            cultivos = ["Vegetación hidrófila natural", "Pastizal natural de bajo (manejo estacional)"]
            recomendaciones = [
                "Preservar como zona de retención hídrica natural, amortiguación de cuenca y biodiversidad.",
                "No realizar canalizaciones clandestinas que trasladen excedentes hídricos a lotes vecinos."
            ]

        if geom.ls_erosion_factor >= 0.45:
            recomendaciones.append(
                f"Control de erosión hídrica (Factor LS={geom.ls_erosion_factor}): sembrar cortando la pendiente principal ({geom.slope_pct}%) o en curvas de nivel."
            )

        if requiere_obras:
            recomendaciones.append(
                f"Sistematización hídrica recomendada (probabilidad JEV: {int(requiere_obras_prob*100)}%): micro-canalización superficial o terrazas de evacuación lenta."
            )

        verdict = AgroVerdict(
            aptitud_productiva=aptitud_key,
            aptitud_productiva_label=aptitud_label,
            aptitud_probabilities=aptitud_probs,
            clase_capacidad_uso_inta=clase_key,
            clase_capacidad_uso_label=clase_label,
            limitante_edafica_codigo=limitante_key,
            limitante_edafica_label=limitante_label,
            indice_productividad_ip=ip_inta,
            manejo_por_ambientes_recomendado=manejo_amb,
            manejo_por_ambientes_prob=manejo_amb_prob,
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
                "clase_inta": verdict.clase_capacidad_uso_label,
                "score_agricola": f"{verdict.score_aptitud_agricola}/100 (IP {ip_inta})",
                "semaforo": verdict.color_semaforo.upper(),
            }
        )

        return verdict, trace
