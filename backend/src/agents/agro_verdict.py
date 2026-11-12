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
    "ganadero_pastizal_bajos": "Apto Ganadería / Pasturas Permanentes",
    "no_agricola_humedal": "No Cultivable (Exclusión Biofísica / Agua / Urbano / Roca)",
}

CLASE_INTA_LABELS = {
    "clase_I_II": "Clases I – II (Agrícola sin limitaciones severas)",
    "clase_III_IV": "Clases III – IV (Agrícola condicional / Rotación conservacionista)",
    "clase_V_VI": "Clases V – VI (Ganadero / Pasturas permanentes o silvopastoril)",
    "clase_VII_VIII": "Clases VII – VIII (No arable / Conservación / Cuerpo hídrico / Urbano)",
}

LIMITANTE_LABELS = {
    "sin_limitante": "Subclase 0 · Sin limitantes críticas",
    "exceso_hidrico_w": "Subclase w · Exceso hídrico, inundación o drenaje impedido",
    "erosion_escorrentia_e": "Subclase e · Susceptibilidad crítica a erosión hídrica o eólica",
    "salinidad_alcalinidad_s": "Subclase s · Restricción edáfica severa (salinidad, arena, roca o tejido urbano)",
}

RESILIENCIA_LABELS = {
    0: "Nula / Muy vulnerable frente a excesos hídricos o limitantes estructurales",
    1: "Resiliencia media (Manejable con manejo por ambientes y rotaciones)",
    2: "Alta resiliencia y estabilidad productiva interanual",
}


class AgroVerdictAgent:
    """
    Agente 3: Clasificación Edáfica, Capacidad de Uso INTA y Dictamen Productivo/Territorial.
    Sintetiza la telemetría real (DEM, WorldCover, Sentinel-2, JRC, OSM) y el perfil hidrológico
    para discriminar mar abierto, ríos, costas, humedales, ciudades, cordones serranos, bosques
    y tierras agropecuarias reales sin reglas geográficas hardcodeadas.
    """

    def __init__(self):
        self.name = "AgroVerdictAgent (JEV System One)"

    async def execute(
        self,
        geo_state: GeospatialState,
        hydro_profile: HydroRiskProfile,
    ) -> tuple[AgroVerdict, AgentExecutionTrace]:
        start_time = time.perf_counter()
        logger.info(f"[{self.name}] Emitiendo dictamen territorial y agronómico para {geo_state.parcel_name}...")

        geom = geo_state.topography.geomorphology
        lc = geo_state.land_cover_breakdown or {}
        wc_water = float(lc.get("agua_permanente_pct", 0.0))
        wc_wetland = float(lc.get("humedal_palustre_pct", 0.0))
        wc_urban = float(lc.get("urbano_edificado_pct", 0.0))
        wc_crop = float(lc.get("cultivos_pct", 0.0))
        wc_grass = float(lc.get("pastizal_herbazal_pct", 0.0))
        wc_bare = float(lc.get("suelo_desnudo_roca_pct", 0.0))
        wc_tree = float(lc.get("bosque_arboreo_pct", 0.0))

        zones_pct = {z.zone_id: z.percentage for z in geo_state.topography.terrain_zones}

        synthesized_state = {
            "parcela": geo_state.parcel_name,
            "ubicacion": f"{geo_state.location_label} (Lat: {geo_state.lat}, Lon: {geo_state.lon})",
            "entorno_detectado": geo_state.environment_type,
            "cuerpo_agua_tipo": geo_state.water_body_type,
            "distancia_agua_m": geo_state.water_distance_m,
            "costa_detectada": geo_state.coast_detected,
            "rio_detectado": geo_state.river_detected,
            "urbano_detectado": geo_state.urban_detected,
            "cobertura_agua_pct": round(wc_water, 1),
            "cobertura_humedal_pct": round(wc_wetland, 1),
            "cobertura_urbana_pct": round(wc_urban, 1),
            "cobertura_cultivo_pct": round(wc_crop, 1),
            "cobertura_pastizal_pct": round(wc_grass, 1),
            "cobertura_suelo_desnudo_pct": round(wc_bare, 1),
            "cobertura_bosque_pct": round(wc_tree, 1),
            "ndvi_sentinel2": geo_state.sentinel2_ndvi,
            "mndwi_sentinel2": geo_state.sentinel2_mndwi,
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
                    "Evaluando la cobertura satelital ESA WorldCover 10m, hidrografía (ríos, lagunas, costas, océano), "
                    "topografía Copernicus DEM e índices espectrales Sentinel-2, ¿cuál es la aptitud real de uso de esta ubicación?"
                ),
                criteria={
                    "agricola_plena": "Apto agricultura continua sobre suelos profundos, drenados y pendientes suaves",
                    "mixto_agricola_ganadero": "Apto rotación agrícola-ganadera conservacionista o uso ribereño con franjas de resguardo",
                    "ganadero_pastizal_bajos": "Apto ganadería extensiva sobre pastizal natural, bajos, piedemonte o manejo silvopastoril",
                    "no_agricola_humedal": "No cultivable: océano/mar abierto, cauce fluvial/laguna, área urbana, borde costero/médano vivo, roca escarpada, suelo desnudo o humedal profundo",
                },
            ),
            "clase_inta": Choice(
                instructions="Según el sistema de Capacidad de Uso de la Tierra (INTA/USDA), ¿en qué grupo de Clases (I a VIII) encuadra este emplazamiento?",
                criteria={
                    "clase_I_II": "Clases I y II: Tierras arables excelentes sin limitaciones severas",
                    "clase_III_IV": "Clases III y IV: Tierras arables con limitaciones moderadas a fuertes (erosión, inundación estacional o borde ribereño)",
                    "clase_V_VI": "Clases V y VI: Tierras no arables aptas para pasturas, ganadería o silvicultura",
                    "clase_VII_VIII": "Clases VII y VIII / Sin suelo agrícola: cuerpos de agua, áreas urbanas, playas/acantilados, humedales profundos o afloramientos rocosos",
                },
            ),
            "limitante_edafica": Choice(
                instructions="¿Cuál es la subclase o factor limitante dominante del terreno según INTA/USDA?",
                criteria={
                    "sin_limitante": "Sin limitaciones edáficas, hídricas ni topográficas relevantes",
                    "exceso_hidrico_w": "Limitación por exceso de agua (w): espejo de agua, cauce fluvial, humedal o napa somera",
                    "erosion_escorrentia_e": "Limitación por erosión y pendiente (e): barranca, acantilado costero o relieve serrano escarpado",
                    "salinidad_alcalinidad_s": "Limitación en perfil o cobertura (s): tejido urbano impermeable, arena/salinidad costera o suelo lítico somero",
                },
            ),
            "resiliencia": Score(
                instructions="¿Cuál es la resiliencia agrícola real de esta ubicación frente a variabilidad climática?",
                criteria=[
                    "Nula aptitud agrícola o vulnerabilidad crítica (medio acuático, urbano, roca, salinidad/arena costera o anegamiento severo)",
                    "Resiliencia media manejable mediante rotaciones, buffers ribereños y ajuste de manejo",
                    "Alta resiliencia agrícola con excelente estabilidad productiva interanual",
                ],
            ),
            "requiere_obras": Noul(
                instructions="¿Requiere el lote obras de sistematización (curvas de nivel, canales de alivio o drenaje) para un manejo productivo seguro?"
            ),
            "manejo_ambientes": Noul(
                instructions="Dada la variabilidad interna (`zonificacion_ambientes_pct`, `amplitud_relieve_m`), ¿se recomienda manejo diferenciado por ambientes productivos?"
            ),
        }

        response = await jev_service.evaluate_system_one(synthesized_state, questions)

        aptitud_key = str(response.choices["aptitud"].choice)
        aptitud_probs = {k: round(v, 3) for k, v in response.choices["aptitud"].probabilities.items()}
        clase_key = str(response.choices["clase_inta"].choice)
        limitante_key = str(response.choices["limitante_edafica"].choice)
        resiliencia_val = max(0, min(2, int(round(response.scores["resiliencia"].score))))
        requiere_obras_prob = round(response.nouls["requiere_obras"].noul, 3)
        manejo_amb_prob = round(response.nouls["manejo_ambientes"].noul, 3)

        env = geo_state.environment_type
        is_water_body = env in ("oceano_mar_abierto", "cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua")
        is_rocky_serrano = env == "relieve_serrano_escarpado" or (not is_water_body and geom.slope_pct >= 8.5)
        is_steep_piedemonte = (not is_rocky_serrano) and (not is_water_body) and (geom.slope_pct >= 4.5 or geom.ls_erosion_factor >= 1.6)
        coast_non_arable = (
            env == "borde_costero_marino"
            and (
                wc_crop < 15.0
                or wc_bare >= 25.0
                or geom.slope_pct >= 6.0
                or (geo_state.water_distance_m is not None and geo_state.water_distance_m <= 180.0)
            )
        )
        wetland_deep = env == "humedal_delta" and (wc_water + wc_wetland >= 45.0 or geo_state.jrc_occurrence_pct >= 40.0)

        # Salvaguardas deterministas por física satelital real (cero coordenadas fijas)
        if env == "oceano_mar_abierto":
            aptitud_key = "no_agricola_humedal"
            aptitud_probs = {"no_agricola_humedal": 0.98, "ganadero_pastizal_bajos": 0.01, "mixto_agricola_ganadero": 0.01, "agricola_plena": 0.0}
            clase_key = "clase_VII_VIII"
            limitante_key = "exceso_hidrico_w"
            resiliencia_val = 0
            requiere_obras_prob = 0.0
            manejo_amb_prob = 0.0
        elif env in ("cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua"):
            aptitud_key = "no_agricola_humedal"
            aptitud_probs = {"no_agricola_humedal": 0.95, "ganadero_pastizal_bajos": 0.03, "mixto_agricola_ganadero": 0.01, "agricola_plena": 0.01}
            clase_key = "clase_VII_VIII"
            limitante_key = "exceso_hidrico_w"
            resiliencia_val = 0
            requiere_obras_prob = 0.05
            manejo_amb_prob = 0.1
        elif env == "area_urbana":
            aptitud_key = "no_agricola_humedal"
            aptitud_probs = {"no_agricola_humedal": 0.94, "ganadero_pastizal_bajos": 0.03, "mixto_agricola_ganadero": 0.02, "agricola_plena": 0.01}
            clase_key = "clase_VII_VIII"
            limitante_key = "salinidad_alcalinidad_s"
            resiliencia_val = 0
            requiere_obras_prob = 0.1
            manejo_amb_prob = 0.05
        elif coast_non_arable or env == "suelo_desnudo_arenal_roca" or wetland_deep:
            aptitud_key = "no_agricola_humedal"
            aptitud_probs = {"no_agricola_humedal": 0.88, "ganadero_pastizal_bajos": 0.09, "mixto_agricola_ganadero": 0.02, "agricola_plena": 0.01}
            clase_key = "clase_VII_VIII"
            limitante_key = "exceso_hidrico_w" if wetland_deep else (
                "erosion_escorrentia_e" if geom.slope_pct >= 5.0 else "salinidad_alcalinidad_s"
            )
            resiliencia_val = 0
            requiere_obras_prob = min(requiere_obras_prob, 0.25)
        elif is_rocky_serrano:
            aptitud_key = "no_agricola_humedal"
            aptitud_probs = {"no_agricola_humedal": 0.85, "ganadero_pastizal_bajos": 0.11, "mixto_agricola_ganadero": 0.03, "agricola_plena": 0.01}
            clase_key = "clase_VII_VIII"
            limitante_key = "erosion_escorrentia_e"
            resiliencia_val = 0
            requiere_obras_prob = min(requiere_obras_prob, 0.25)
        elif env in ("humedal_delta", "bosque_monte"):
            if aptitud_key == "agricola_plena":
                aptitud_key = "ganadero_pastizal_bajos"
            if clase_key == "clase_I_II":
                clase_key = "clase_V_VI"
            resiliencia_val = min(resiliencia_val, 1)
        elif env in ("lote_ribereño_fluvial", "borde_costero_marino"):
            # Cercanía directa a cauce fluvial o frente costero excluye agricultura intensiva sin restricciones
            if aptitud_key == "agricola_plena":
                aptitud_key = "mixto_agricola_ganadero"
            if clase_key == "clase_I_II":
                clase_key = "clase_III_IV"
            resiliencia_val = min(resiliencia_val, 1)
        elif is_steep_piedemonte:
            if aptitud_key == "agricola_plena":
                aptitud_key = "ganadero_pastizal_bajos" if (geom.slope_pct >= 6.0 and wc_crop < 35.0) else "mixto_agricola_ganadero"
            if clase_key in ("clase_I_II", "clase_III_IV") and geom.slope_pct >= 5.5 and wc_crop < 35.0:
                clase_key = "clase_V_VI"
            if limitante_key == "sin_limitante":
                limitante_key = "erosion_escorrentia_e"
            resiliencia_val = min(resiliencia_val, 1)

        aptitud_label = APTITUD_LABELS.get(aptitud_key, aptitud_key)
        clase_label = CLASE_INTA_LABELS.get(clase_key, clase_key)
        limitante_label = LIMITANTE_LABELS.get(limitante_key, limitante_key)
        resiliencia_label = RESILIENCIA_LABELS.get(resiliencia_val, "Moderada")

        if env == "oceano_mar_abierto":
            aptitud_label = "No Cultivable (Mar Abierto / Aguas Oceánicas)"
            clase_label = "Sin Suelo Agrícola · Plataforma Marina"
            limitante_label = "Medio Oceánico Permanente (Cota 0 msnm)"
            resiliencia_label = "Inaplicable en medio marino"
        elif env in ("cuerpo_agua_abierto", "cauce_fluvial_rio"):
            aptitud_label = "No Cultivable (Cauce Fluvial / Estuario Activo)"
            clase_label = "Clases VIII · Cuerpo de Agua Superficial"
            limitante_label = "Subclase w · Espejo o curso de agua permanente"
        elif env == "laguna_cuerpo_agua":
            aptitud_label = "No Cultivable (Laguna / Cubeta Lacustre Permanente)"
            clase_label = "Clases VIII · Reserva Hídrica Superficial"
            limitante_label = "Subclase w · Sumergido permanentemente (JRC / WorldCover)"
        elif env == "area_urbana":
            aptitud_label = f"No Cultivable (Área Urbana Consolidada · {wc_urban:.0f}% edificado)"
            clase_label = "Uso Urbano / Infraestructura Impermeable (No Rural)"
            limitante_label = "Superficie Antrópica Impermeable (WorldCover 50)"
        elif coast_non_arable:
            aptitud_label = "No Cultivable (Frente Costero / Playa / Acantilado Marino)"
            clase_label = "Clases VII – VIII (Franja costera y protección dunaria)"
            limitante_label = "Subclase s/e · Salinidad marina, arena móvil o barranca litoral"
        elif is_rocky_serrano:
            aptitud_label = "No Cultivable (Relieve Serrano Escarpado / Roca)"
            clase_label = "Clases VII – VIII (Suelos líticos someros / Reserva serrana)"
            limitante_label = "Subclase e/s · Pendiente crítica y contacto lítico rocoso"
            resiliencia_label = "Nula aptitud arable (Pendiente escarpada y suelo somero)"
        elif env == "bosque_monte" and aptitud_key == "ganadero_pastizal_bajos":
            aptitud_label = "Área Boscosa / Aptitud Silvopastoril o Conservación Forestal"
            clase_label = "Clases V – VI (Cobertura arbórea densa · Ley de Bosques)"

        requiere_obras = requiere_obras_prob >= 0.5
        manejo_amb = manejo_amb_prob >= 0.45

        # Score de Aptitud Agrícola (0 - 100) calibrado por telemetría real
        loma_media_pct = zones_pct.get("loma_alta", 25.0) + zones_pct.get("media_loma", 25.0)

        if env == "oceano_mar_abierto":
            final_score = 0
            ip_inta = 0
        elif env in ("cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua", "area_urbana"):
            final_score = 2 if env == "cauce_fluvial_rio" else 0
            ip_inta = 0
        elif coast_non_arable or env == "suelo_desnudo_arenal_roca":
            final_score = max(6, min(20, int(round(18 - wc_water * 0.15 - min(10.0, geom.slope_pct)))))
            ip_inta = max(2, min(14, int(final_score * 0.7)))
        elif is_rocky_serrano:
            final_score = max(6, min(22, int(round(24 - max(0.0, geom.slope_pct - 6.0) * 1.4))))
            ip_inta = max(4, min(16, int(round(final_score * 0.8))))
        elif wetland_deep:
            final_score = max(8, min(24, int(round(28 - hydro_profile.riesgo_inundacion_severo_prob * 18))))
            ip_inta = max(5, min(20, int(final_score * 0.8)))
        else:
            base_score = (
                92 if aptitud_key == "agricola_plena"
                else (68 if aptitud_key == "mixto_agricola_ganadero" else (46 if aptitud_key == "ganadero_pastizal_bajos" else 16))
            )
            penalty_risk = int(hydro_profile.riesgo_inundacion_severo_prob * 28)
            penalty_topo = min(22, int(max(0.0, geom.slope_pct - 3.0) * 2.8)) if is_steep_piedemonte else 0
            penalty_coast = 12 if env == "borde_costero_marino" else 0
            penalty_river = 8 if env == "lote_ribereño_fluvial" else 0
            crop_bonus = 4 if wc_crop >= 60.0 else (-5 if wc_crop < 10.0 and aptitud_key in ("agricola_plena", "mixto_agricola_ganadero") else 0)
            resilience_bonus = resiliencia_val * 6
            final_score = max(
                10,
                min(98, base_score - penalty_risk - penalty_topo - penalty_coast - penalty_river + crop_bonus + resilience_bonus),
            )
            ip_inta = int(round(max(6.0, min(96.0, final_score * 0.74 + loma_media_pct * 0.24))))

        if final_score >= 75:
            color = "verde"
        elif final_score >= 30:
            color = "amarillo"
        else:
            color = "rojo"

        recomendaciones: List[str] = []
        cultivos: List[str] = []

        if env == "oceano_mar_abierto":
            dictamen = (
                f"Coordenada ubicada en MAR ABIERTO / AGUAS OCEÁNICAS ({final_score}/100 · IP INTA {ip_inta}). "
                f"Cota {geo_state.elevation_m} msnm sin plataforma continental emergida ni perfil de suelo agronómico."
            )
            cultivos = ["Inapto para cultivos agrícolas (Medio Marino)"]
            recomendaciones = [
                "No corresponde análisis agronómico terrestre: el punto seleccionado recae fuera de la línea de costa sobre océano abierto.",
                "Desplace el marcador hacia tierra firme continental si desea evaluar una parcela productiva.",
            ]
        elif env in ("cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua"):
            tipo_agua_txt = (
                "CAUCE FLUVIAL / RÍO" if env == "cauce_fluvial_rio"
                else ("LAGUNA / EMBALSE" if env == "laguna_cuerpo_agua" else "CUERPO DE AGUA / ESTUARIO")
            )
            dictamen = (
                f"Terreno NO CULTIVABLE sobre {tipo_agua_txt} ({final_score}/100 · {geo_state.location_label}). "
                f"Teledetección WorldCover ({wc_water:.1f}% agua), MNDWI ({geo_state.sentinel2_mndwi:+.2f}) y JRC ({geo_state.jrc_occurrence_pct:.0f}% histórico) confirman lámina de agua permanente."
            )
            cultivos = ["Inapto para agricultura (Cuerpo de agua activo)", "Vegetación ribereña e hidrófila de protección"]
            recomendaciones = [
                "Exclusión total de uso agrícola: la coordenada está dentro del espejo de agua o lecho activo.",
                "Mantener franja vegetada ribereña en márgenes firmes para estabilizar barrancas y retener sedimentos.",
            ]
        elif env == "area_urbana":
            dictamen = (
                f"Ubicación NO CULTIVABLE: ÁREA URBANA CONSOLIDADA en {geo_state.location_label} ({final_score}/100). "
                f"ESA WorldCover 10m detecta {wc_urban:.1f}% de superficie edificada/impermeabilizada (sin horizonte agrícola activo)."
            )
            cultivos = ["Inapto (Tejido Urbano Consolidado)", "Infraestructura verde y arbolado urbano"]
            recomendaciones = [
                "La coordenada seleccionada corresponde a planta urbana o zona periurbana edificada; sin aptitud para cultivos extensivos.",
                f"Considerar escorrentía superficial concentrada (riesgo pluvial {int(hydro_profile.riesgo_inundacion_severo_prob * 100)}%) y restricción legal periurbana.",
            ]
        elif coast_non_arable:
            dist_txt = f"a {geo_state.water_distance_m:.0f} m" if geo_state.water_distance_m is not None else "en contacto inmediato"
            dictamen = (
                f"Terreno NO CULTIVABLE en BORDE COSTERO MARINO ({final_score}/100 · {geo_state.location_label}). "
                f"Línea de costa detectada {dist_txt} ({wc_water:.1f}% agua litoral, cota {geo_state.elevation_m} msnm, pend. {geom.slope_pct}%). "
                "Condicionado por dinámica litoral, médanos, aerosol salino o barranca costera erosionable."
            )
            cultivos = ["Inapto para agricultura en franja costera", "Psamófilas fijadoras de médanos (Spartina / Cortaderia)"]
            recomendaciones = [
                "Preservar la faja litoral y cordón dunario/acantilado contra erosión eólica y marejadas.",
                "La alta exposición salina y fragilidad costera impiden implantar cultivos extensivos convencionales.",
            ]
        elif env == "suelo_desnudo_arenal_roca":
            dictamen = (
                f"Terreno NO CULTIVABLE por sustrato mineral desnudo ({final_score}/100 · {geo_state.location_label}). "
                f"ESA WorldCover registra {wc_bare:.1f}% de suelo desnudo/roca/arenal (NDVI {geo_state.sentinel2_ndvi:+.2f})."
            )
            cultivos = ["Inapto para agricultura (Arenal / Salar / Sustrato mineral)"]
            recomendaciones = [
                "Sustrato carente de cobertura vegetal y materia orgánica útil (dunas vivas, salinas o afloramiento mineral).",
                "Evaluar eventual estabilización con vegetación halófila o psamófila autóctona antes de cualquier intervención.",
            ]
        elif is_rocky_serrano:
            dictamen = (
                f"Terreno NO CULTIVABLE por relieve serrano escarpado ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"{geo_state.location_label}: cota {geo_state.elevation_m} msnm, pendiente {geom.slope_pct}% (máx {geom.max_slope_pct}%), "
                f"desnivel Δ {geom.relief_amplitude_m} m y Factor USLE LS={geom.ls_erosion_factor}. Inapto para laboreo agrícola ({clase_label})."
            )
            cultivos = ["Inapto para cultivos agrícolas", "Pastizal serrano nativo (conservación)", "Reserva natural de cuenca alta"]
            recomendaciones = [
                "Exclusión absoluta de roturación o labranza mecánica por pendiente crítica y alta susceptibilidad a erosión laminar y en cárcavas.",
                "Destinar a conservación de pastizal serrano nativo, recarga hídrica y manejo pastoral de mínima carga en valles basales.",
            ]
        elif env == "lote_ribereño_fluvial":
            dist_txt = f"{geo_state.water_distance_m:.0f} m" if geo_state.water_distance_m is not None else "<500 m"
            dictamen = (
                f"Parcela RIBEREÑA FLUVIAL de aptitud condicionada ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Curso fluvial detectado a {dist_txt} del centro ({wc_water:.1f}% agua superficial en encuadre, {wc_crop:.1f}% cultivos). "
                f"Requiere franja buffer no cultivable y manejo conservacionista ({clase_label})."
            )
            if aptitud_key == "ganadero_pastizal_bajos":
                cultivos = ["Pasturas tolerantes a excesos (Lotus / Festuca / Agropiro)", "Bosque o pastizal ribereño protector"]
            else:
                cultivos = ["Maíz / Sorgo en terrazas altas (>50 m del cauce)", "Pasturas perennes consociadas en planicie aluvial", "Trigo / Cultivos de cobertura"]
            recomendaciones = [
                f"Respetar una franja buffer ribereña vegetada de al menos 30–50 metros desde el borde del cauce detectado (distancia actual: {dist_txt}).",
                "Evitar aplicación de agroquímicos y laboreo en sectores de valle de inundación periódica para prevenir contaminación y erosión de márgenes.",
                "Concentrar los cultivos anuales exclusivamente en las terrazas altas del lote y destinar los bajos ribereños a pasturas perennes.",
            ]
        elif env == "borde_costero_marino":
            dictamen = (
                f"Parcela interior de transición COSTERA ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"{wc_crop:.1f}% cultivos activos con costa marina a {geo_state.water_distance_m or 0:.0f} m. "
                "Aptitud restringida por viento salino, erosión eólica y menor retención hídrica."
            )
            cultivos = ["Cebada / Trigo con cobertura", "Girasol", "Avena / Vicia de cobertura", "Pasturas perennes (Festuca / Alfalfa)"]
            recomendaciones = [
                "Mantener cobertura permanente de rastrojo o cultivos de servicio para frenar la erosión eólica costera.",
                "Implementar cortinas forestales rompeviento frente al cuadrante marino y priorizar cultivos tolerantes a salinidad moderada.",
            ]
        elif env == "bosque_monte":
            dictamen = (
                f"Área con predominio ARBÓREO / MONTE ({final_score}/100 · {wc_tree:.1f}% cobertura forestal WorldCover). "
                f"{clase_label}. Incompatible con desmonte o agricultura extensiva convencional."
            )
            cultivos = ["Manejo silvopastoril sustentable", "Pasturas megatérmicas o templadas bajo dosel", "Conservación de bosque nativo"]
            recomendaciones = [
                "Preservar la masa boscosa existente respetando normativa forestal vigente y corredores biológicos.",
                "Si el ordenamiento territorial lo permite, restringir la actividad productiva a pastoreo rotativo de bajo impacto (silvopastoril).",
            ]
        elif aptitud_key == "agricola_plena":
            dictamen = (
                f"Lote de alto potencial agronómico ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"{geo_state.location_label}: {wc_crop:.1f}% superficie agrícola (NDVI {geo_state.sentinel2_ndvi:+.2f}), "
                f"predominio de {clase_label} con {round(loma_media_pct, 1)}% en lomas y medias lomas bien drenadas."
            )
            cultivos = ["Soja de 1ª", "Maíz temprano", "Trigo / Soja 2ª", "Cebada cervecera", "Girasol"]
            recomendaciones = [
                "Mantener esquema de siembra directa con cobertura permanente de rastrojo.",
                "Rotación equitativa gramíneas/oleaginosas para conservar infiltración y balance de carbono edáfico.",
                "Aplicar fertilización variable diferenciando ambientes de loma alta y media loma.",
            ]
        elif aptitud_key == "mixto_agricola_ganadero":
            dictamen = (
                f"Lote de aptitud MIXTA ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"{clase_label} ({wc_crop:.1f}% cultivo, {wc_grass:.1f}% pastizal). Permite agricultura conservacionista en sectores altos "
                f"({zones_pct.get('loma_alta', 0)}%) y pasturas perennes en bajos o sectores de mayor pendiente."
            )
            cultivos = ["Trigo / Cebada en contorno", "Girasol", "Sorgo granífero / forrajero", "Pasturas de Alfalfa / Festuca"]
            recomendaciones = [
                "Zonificar el lote separando sectores bien drenados (agrícola) de bajos o laderas (forrajero).",
                "Sembrar cortando la pendiente principal para reducir escorrentía y pérdida de suelo.",
                "Evitar barbechos desnudos manteniendo cobertura viva o rastrojo anclado todo el año.",
            ]
        elif aptitud_key == "ganadero_pastizal_bajos":
            dictamen = (
                f"Lote con limitantes para agricultura anual ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Corresponde a {clase_label} ({limitante_label}). Uso recomendado ganadero sobre pasturas adaptadas o pastizal natural."
            )
            cultivos = ["Lotus tenuis / corniculatus", "Agropiro alargado", "Festuca arundinacea", "Pastizal natural manejado"]
            recomendaciones = [
                "Evitar laboreo convencional para no acelerar mineralización, salinización ni erosión superficial.",
                "Ajustar carga animal rotativa y conservar cobertura herbácea densa durante períodos críticos.",
            ]
        else:
            dictamen = (
                f"Terreno con limitación hídrica severa / humedal profundo ({final_score}/100 · IP INTA ~{ip_inta}). "
                f"Alta saturación ({wc_wetland + wc_water:.1f}% humedal/agua, JRC {geo_state.jrc_occurrence_pct:.0f}%). Restricción absoluta para laboreo agrícola."
            )
            cultivos = ["Vegetación hidrófila / palustre nativa", "Ganadería extensiva estacional muy controlada"]
            recomendaciones = [
                "Preservar como humedal natural de amortiguación de crecidas, recarga hídrica y biodiversidad.",
                "No ejecutar drenajes artificiales ni canalizaciones que alteren la dinámica natural de la cuenca.",
            ]

        if (
            geom.ls_erosion_factor >= 0.45
            and not is_rocky_serrano
            and not is_water_body
            and env != "area_urbana"
            and not coast_non_arable
        ):
            recomendaciones.append(
                f"Control de erosión hídrica (Factor LS={geom.ls_erosion_factor}): orientar líneas de siembra cortando la pendiente ({geom.slope_pct}%)."
            )

        if requiere_obras and not is_water_body and env != "area_urbana" and not is_rocky_serrano:
            recomendaciones.append(
                f"Sistematización hídrica sugerida (probabilidad JEV {int(requiere_obras_prob * 100)}%): micro-desagües empastados o terrazas de evacuación controlada."
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
            cultivos_sugeridos=cultivos,
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
            },
        )

        return verdict, trace
