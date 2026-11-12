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
    3: "Depresión crítica / Acumulación severa",
}

MECANISMO_LABELS = {
    "desborde_cuenca": "Desborde fluvial, lagunar o dinámica costera/marina",
    "escurrimiento_pluvial_lento": "Estancamiento pluvial por escasa pendiente o impermeabilización",
    "afloramiento_napa_freatica": "Afloramiento / saturación de napa freática somera",
    "sin_anegamiento": "Relieve drenado sin riesgo significativo de anegamiento",
}


def _describe_hydrography(geo_state: GeospatialState) -> str:
    env_type = geo_state.environment_type
    lc = geo_state.land_cover_breakdown or {}
    wc_water = float(lc.get("agua_permanente_pct", 0.0))
    wc_wetland = float(lc.get("humedal_palustre_pct", 0.0))
    dist_txt = f"a {geo_state.water_distance_m:.0f} m" if geo_state.water_distance_m is not None else "en el entorno"

    if env_type == "oceano_mar_abierto":
        return "Plataforma Marina / Mar Abierto permanente (Cota 0 msnm)"
    if env_type in ("cauce_fluvial_rio", "cuerpo_agua_abierto"):
        return f"Cauce fluvial o estuarino activo en el punto ({wc_water:.1f}% agua WorldCover, MNDWI {geo_state.sentinel2_mndwi:+.2f})"
    if env_type == "laguna_cuerpo_agua":
        return f"Espejo lacustre / laguna permanente ({wc_water:.1f}% agua WorldCover, JRC {geo_state.jrc_occurrence_pct:.0f}%)"
    if env_type == "borde_costero_marino":
        return f"Línea de costa marina / estuario detectada {dist_txt} ({wc_water:.1f}% agua litoral)"
    if env_type == "lote_ribereño_fluvial":
        return f"Curso fluvial / río o arroyo detectado {dist_txt} del centro ({wc_water:.1f}% agua superficial)"
    if env_type == "humedal_delta":
        return f"Humedal / Bañado activo ({wc_wetland:.1f}% palustre, {wc_water:.1f}% espejos de agua)"
    if wc_water >= 0.5 or geo_state.jrc_occurrence_pct >= 5.0:
        return f"Espejos o trazas hídricas menores detectadas ({wc_water:.1f}% WorldCover, JRC {geo_state.jrc_occurrence_pct:.1f}%)"
    return "Sin cursos fluviales ni frentes costeros significativos en el radio analizado"


class HydroRiskAgent:
    """
    Agente 2: Evaluación de Riesgo Hidrológico, Costero y Geomorfológico.
    Integra señales satelitales reales (DEM, JRC, WorldCover, MNDWI, SAR, proximidad a ríos/costas)
    y utiliza JEV (TypeSafe System One) para cuantificar probabilidad y mecanismo hídrico.
    """

    def __init__(self):
        self.name = "HydroRiskAgent (JEV System One)"

    async def execute(self, geo_state: GeospatialState) -> tuple[HydroRiskProfile, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Evaluando riesgo hidrológico con JEV para {geo_state.parcel_name}...")

        geom = geo_state.topography.geomorphology
        lc = geo_state.land_cover_breakdown or {}
        zones_summary = {
            z.zone_id: f"{z.percentage}% ({z.area_ha} ha)"
            for z in geo_state.topography.terrain_zones
        }

        jev_state = {
            "parcela": geo_state.parcel_name,
            "ubicacion": f"{geo_state.location_label} (Lat: {geo_state.lat}, Lon: {geo_state.lon})",
            "entorno_detectado": geo_state.environment_type,
            "cuerpo_agua_tipo": geo_state.water_body_type,
            "distancia_agua_m": geo_state.water_distance_m,
            "costa_detectada": geo_state.coast_detected,
            "rio_detectado": geo_state.river_detected,
            "urbano_detectado": geo_state.urban_detected,
            "cobertura_agua_pct": round(float(lc.get("agua_permanente_pct", 0.0)), 1),
            "cobertura_humedal_pct": round(float(lc.get("humedal_palustre_pct", 0.0)), 1),
            "cobertura_urbana_pct": round(float(lc.get("urbano_edificado_pct", 0.0)), 1),
            "cobertura_cultivo_pct": round(float(lc.get("cultivos_pct", 0.0)), 1),
            "cobertura_pastizal_pct": round(float(lc.get("pastizal_herbazal_pct", 0.0)), 1),
            "cobertura_suelo_desnudo_pct": round(float(lc.get("suelo_desnudo_roca_pct", 0.0)), 1),
            "cobertura_bosque_pct": round(float(lc.get("bosque_arboreo_pct", 0.0)), 1),
            "unidad_geomorfologica": geom.region_geomorphology,
            "red_drenaje": geom.drainage_network_type,
            "cota_elevacion_msnm": geo_state.elevation_m,
            "amplitud_relieve_m": geom.relief_amplitude_m,
            "pendiente_grados": geo_state.slope_deg,
            "pendiente_porcentaje": geom.slope_pct,
            "factor_erosion_usle_ls": geom.ls_erosion_factor,
            "indice_depresion_relativa_0_a_1": geo_state.relative_depression_score,
            "indice_humedad_topografica_twi": geom.twi_value,
            "indice_posicion_topografica_tpi_m": geom.tpi_value_m,
            "profundidad_napa_freatica_estimada_m": geom.estimated_water_table_depth_m,
            "distribucion_ambientes_lote": zones_summary,
            "recurrencia_historica_agua_jrc_pct": geo_state.jrc_occurrence_pct,
            "estacionalidad_agua": geo_state.jrc_seasonality,
            "retrodispersion_radar_sar_db": geo_state.sar_backscatter_db,
            "indice_humedad_ndwi": geo_state.sentinel2_ndwi,
            "mndwi_sentinel2": geo_state.sentinel2_mndwi,
            "ndvi_sentinel2": geo_state.sentinel2_ndvi,
        }

        questions = {
            "riesgo_severo": Noul(
                instructions=(
                    "Evaluando el entorno real detectado (`entorno_detectado`, proximidad a ríos/costas, cobertura de agua WorldCover, "
                    "MNDWI Sentinel-2, recurrencia JRC, TWI y DEM), ¿presenta esta ubicación presencia permanente de agua o "
                    "alta probabilidad de anegamiento, desborde fluvial/marino o saturación crítica?"
                )
            ),
            "vulnerabilidad_topografica": Score(
                instructions="¿Cuál es el grado de vulnerabilidad topográfica o exposición hídrica directa del emplazamiento?",
                criteria=[
                    "Loma o relieve elevado con drenaje rápido sin acumulación hídrica",
                    "Plano suave o tejido tendido con escurrimiento moderado a lento",
                    "Terraza ribereña, franja costera baja o cubeta intermedia expuesta a excesos",
                    "Espejo de agua permanente (mar, río, laguna), humedal o depresión crítica inundable",
                ],
            ),
            "mecanismo_hidrico": Choice(
                instructions="¿Cuál es el mecanismo hidrológico o marino dominante en esta coordenada?",
                criteria={
                    "desborde_cuenca": "Presencia directa o desborde de ríos, arroyos, lagunas o dinámica costera/marina",
                    "escurrimiento_pluvial_lento": "Escurrimiento plano lento por escasa pendiente o impermeabilización urbana",
                    "afloramiento_napa_freatica": "Saturación por napa freática somera en humedales o bajos profundos",
                    "sin_anegamiento": "Relieve alto o inclinado sin riesgo significativo de anegamiento",
                },
            ),
        }

        response = await jev_service.evaluate_system_one(jev_state, questions)

        noul_val = round(response.nouls["riesgo_severo"].noul, 3)
        score_val = max(0, min(3, int(round(response.scores["vulnerabilidad_topografica"].score))))
        score_label = SCORE_LABELS.get(score_val, "Moderado")

        choice_obj = response.choices["mecanismo_hidrico"]
        choice_key = str(choice_obj.choice)
        choice_label = MECANISMO_LABELS.get(choice_key, choice_key)
        choice_probs = {k: round(v, 3) for k, v in choice_obj.probabilities.items()}
        confidence = round(float(choice_obj.confidence or 0.9), 3)

        env = geo_state.environment_type
        wc_water = float(lc.get("agua_permanente_pct", 0.0))
        wc_urban = float(lc.get("urbano_edificado_pct", 0.0))
        wc_wetland = float(lc.get("humedal_palustre_pct", 0.0))
        hidrografia = _describe_hydrography(geo_state)

        # Consistencia biofísica por entorno real
        if env == "oceano_mar_abierto":
            noul_val = 0.99
            score_val = 3
            score_label = "Mar Abierto / Plataforma Marina (Cota 0 msnm)"
            choice_key = "desborde_cuenca"
            choice_label = "Dinámica Marina Permanente / Océano Abierto"
            choice_probs = {"desborde_cuenca": 0.96, "afloramiento_napa_freatica": 0.02, "escurrimiento_pluvial_lento": 0.01, "sin_anegamiento": 0.01}
            resumen = (
                f"Coordenada sobre aguas marinas/oceánicas abiertas ({geo_state.location_label}, cota {geo_state.elevation_m} msnm). "
                "Superficie hídrica permanente sin suelo continental ni drenaje terrestre."
            )
        elif env in ("cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua"):
            noul_val = max(noul_val, 0.96)
            score_val = 3
            score_label = "Cuerpo de Agua Activo / Cauce Sumergido"
            choice_key = "desborde_cuenca"
            choice_label = (
                "Corriente Fluvial / Estuarina Permanente"
                if env in ("cauce_fluvial_rio", "cuerpo_agua_abierto")
                else "Espejo Lacustre / Laguna Permanente"
            )
            choice_probs = {"desborde_cuenca": 0.88, "afloramiento_napa_freatica": 0.07, "escurrimiento_pluvial_lento": 0.04, "sin_anegamiento": 0.01}
            resumen = (
                f"Punto ubicado directamente dentro de un cuerpo de agua superficial ({geo_state.location_label}). "
                f"Cobertura líquida {wc_water:.1f}% (WorldCover 80), MNDWI {geo_state.sentinel2_mndwi:+.2f} y recurrencia JRC {geo_state.jrc_occurrence_pct:.0f}%."
            )
        elif env == "borde_costero_marino":
            score_label = "Frente Costero Litoral / Acantilado o Playa"
            choice_key = "desborde_cuenca"
            choice_label = "Dinámica Litoral Marina / Mareas, Oleaje y Aerosol Salino"
            dist_m = f"{geo_state.water_distance_m:.0f} m" if geo_state.water_distance_m is not None else "inmediato"
            resumen = (
                f"Emplazamiento costero con frente marino detectado a {dist_m} ({wc_water:.1f}% agua en encuadre, cota {geo_state.elevation_m} msnm, "
                f"pendiente {geom.slope_pct}%). Exposición directa a erosión litoral, vientos marinos e intrusión salina."
            )
        elif env == "lote_ribereño_fluvial":
            score_val = max(2, score_val)
            score_label = "Terraza Ribereña / Planicie Aluvial Adyacente a Cauce"
            choice_key = "desborde_cuenca"
            choice_label = "Desborde Fluvial / Exposición a Crecidas de Río o Arroyo"
            dist_m = f"{geo_state.water_distance_m:.0f} m" if geo_state.water_distance_m is not None else "<500 m"
            resumen = (
                f"Parcela ribereña con curso fluvial activo detectado a {dist_m} del centro ({wc_water:.1f}% agua, "
                f"JRC {geo_state.jrc_occurrence_pct:.0f}%). Riesgo de desborde en crecidas extraordinarias ({int(noul_val * 100)}%)."
            )
        elif env == "humedal_delta":
            noul_val = max(noul_val, 0.72)
            score_val = 3
            score_label = "Humedal / Bañado Palustre de Saturación Prolongada"
            resumen = (
                f"Ambiente de humedal o planicie de inundación ({wc_wetland:.1f}% palustre, {wc_water:.1f}% espejos de agua, "
                f"JRC {geo_state.jrc_occurrence_pct:.0f}%). Alta recurrencia de anegamiento ({int(noul_val * 100)}%)."
            )
        elif env == "area_urbana":
            score_label = "Superficie Urbana Impermeable (Red Pluvial)"
            choice_key = "escurrimiento_pluvial_lento" if choice_key == "sin_anegamiento" and noul_val >= 0.25 else choice_key
            choice_label = "Escorrentía Urbana sobre Tejido Impermeable"
            resumen = (
                f"Zona urbana consolidada en {geo_state.location_label} ({wc_urban:.0f}% superficie edificada WorldCover 50). "
                f"Riesgo de anegamiento pluvial urbano estimado en {int(noul_val * 100)}% según cota ({geo_state.elevation_m} m) y depresión relativa."
            )
        elif env == "relieve_serrano_escarpado" or geom.slope_pct >= 8.5:
            noul_val = min(noul_val, 0.18)
            score_val = 0
            score_label = "Relieve Serrano Escarpado / Escorrentía Torrencial"
            choice_key = "sin_anegamiento"
            choice_label = "Escorrentía torrencial rápida en ladera (riesgo erosivo, no inundación)"
            resumen = (
                f"Riesgo de anegamiento nulo ({int(noul_val * 100)}%), pero escorrentía superficial torrencial "
                f"por fuerte pendiente ({geom.slope_pct}%, desnivel Δ {geom.relief_amplitude_m} m, Factor LS {geom.ls_erosion_factor})."
            )
        elif noul_val > 0.65:
            resumen = (
                f"Riesgo hídrico crítico ({int(noul_val * 100)}%). Sujeto a {choice_label.lower()} "
                f"con drenaje deficiente (TWI {geom.twi_value}, JRC {geo_state.jrc_occurrence_pct:.1f}%)."
            )
        elif noul_val > 0.35:
            resumen = (
                f"Riesgo hídrico moderado/intermedio ({int(noul_val * 100)}%). Vulnerabilidad en ciclos húmedos "
                f"(Napa est. {geom.estimated_water_table_depth_m} m, pendiente {geom.slope_pct}%)."
            )
        else:
            resumen = (
                f"Riesgo hídrico bajo ({int(noul_val * 100)}%). Buena evacuación topográfica y drenaje favorable "
                f"(Pendiente {geom.slope_pct}%, TWI {geom.twi_value})."
            )

        profile = HydroRiskProfile(
            riesgo_inundacion_severo_prob=noul_val,
            vulnerabilidad_topografica_score=score_val,
            vulnerabilidad_topografica_label=score_label,
            mecanismo_hidrico_dominante=choice_key,
            mecanismo_hidrico_label=choice_label,
            mecanismo_probabilities=choice_probs,
            confidence=confidence,
            resumen_hidrologico=resumen,
            hidrografia_detectada=hidrografia,
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        trace = AgentExecutionTrace(
            agent_id="agent_2_hydro_risk",
            agent_name=self.name,
            status="completed",
            duration_ms=elapsed_ms,
            highlights={
                "hidrografia": hidrografia,
                "prob_inundacion": f"{int(profile.riesgo_inundacion_severo_prob * 100)}%",
                "topografia": profile.vulnerabilidad_topografica_label,
                "mecanismo": profile.mecanismo_hidrico_label,
            },
        )

        return profile, trace
