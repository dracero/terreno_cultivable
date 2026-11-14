import math
from typing import List, Dict, Any, Tuple
from ..schemas import (
    ContourLine,
    FlowVector,
    ProfilePoint,
    ElevationProfile,
    TerrainZoneStat,
    GeomorphologyMetrics,
    TopographicAnalysisData,
)
from .geodesy_engine import compute_geodetic_summary


def _cardinal_from_azimuth(deg: float, slope_pct: float) -> str:
    if slope_pct < 0.08:
        return "Plano horizontal (sin exposición dominante)"
    dirs = [
        ("N (Solana cálida)", 0),
        ("NE (Templada húmeda)", 45),
        ("E (Mañana templada)", 90),
        ("SE (Fresca húmeda)", 135),
        ("S (Umbría fría / menor evapotranspiración)", 180),
        ("SO (Umbría ventosa)", 225),
        ("O (Tarde cálida)", 270),
        ("NO (Solana cálida de tarde)", 315),
    ]
    idx = int(((deg + 22.5) % 360) // 45)
    return dirs[idx][0]


def _marching_squares_contours(
    lats: List[float],
    lons: List[float],
    z_grid: List[List[float]],
    interval: float,
) -> List[ContourLine]:
    """
    Extrae isolíneas (curvas de nivel) mediante interpolación lineal Marching Squares
    y conecta segmentos adyacentes en polilíneas continuas para graficar en Leaflet.
    """
    rows = len(lats)
    cols = len(lons)
    z_flat = [val for row in z_grid for val in row]
    z_min, z_max = min(z_flat), max(z_flat)

    # Ajustar intervalo para tener entre 5 y 14 niveles de curvas de nivel legibles
    span = max(0.4, z_max - z_min)
    if span / interval > 14:
        interval = round(span / 10.0, 1) or 0.5
    elif span / interval < 4:
        interval = max(0.1, round(span / 6.0, 2))

    start_level = math.ceil(z_min / interval) * interval
    levels: List[float] = []
    lvl = start_level
    while lvl < z_max:
        levels.append(round(lvl, 2))
        lvl += interval

    def interp(p1: Tuple[float, float], p2: Tuple[float, float], v1: float, v2: float, target: float) -> Tuple[float, float]:
        if abs(v2 - v1) < 1e-6:
            return ((p1[0] + p2[0]) * 0.5, (p1[1] + p2[1]) * 0.5)
        t = max(0.0, min(1.0, (target - v1) / (v2 - v1)))
        return (round(p1[0] + t * (p2[0] - p1[0]), 6), round(p1[1] + t * (p2[1] - p1[1]), 6))

    contours: List[ContourLine] = []

    for idx_lvl, level in enumerate(levels):
        segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
        for r in range(rows - 1):
            for c in range(cols - 1):
                # Vértices de la celda: BL(r,c), BR(r,c+1), TR(r+1,c+1), TL(r+1,c)
                v_bl = z_grid[r][c]
                v_br = z_grid[r][c + 1]
                v_tr = z_grid[r + 1][c + 1]
                v_tl = z_grid[r + 1][c]

                p_bl = (lats[r], lons[c])
                p_br = (lats[r], lons[c + 1])
                p_tr = (lats[r + 1], lons[c + 1])
                p_tl = (lats[r + 1], lons[c])

                case_val = (
                    (1 if v_bl >= level else 0)
                    | (2 if v_br >= level else 0)
                    | (4 if v_tr >= level else 0)
                    | (8 if v_tl >= level else 0)
                )
                if case_val in (0, 15):
                    continue

                e_bottom = interp(p_bl, p_br, v_bl, v_br, level)
                e_right = interp(p_br, p_tr, v_br, v_tr, level)
                e_top = interp(p_tl, p_tr, v_tl, v_tr, level)
                e_left = interp(p_bl, p_tl, v_bl, v_tl, level)

                if case_val in (1, 14):
                    segments.append((e_left, e_bottom))
                elif case_val in (2, 13):
                    segments.append((e_bottom, e_right))
                elif case_val in (3, 12):
                    segments.append((e_left, e_right))
                elif case_val in (4, 11):
                    segments.append((e_top, e_right))
                elif case_val == 5:
                    segments.append((e_left, e_top))
                    segments.append((e_bottom, e_right))
                elif case_val in (6, 9):
                    segments.append((e_bottom, e_top))
                elif case_val in (7, 8):
                    segments.append((e_left, e_top))
                elif case_val == 10:
                    segments.append((e_left, e_bottom))
                    segments.append((e_top, e_right))

        # Unir segmentos contiguos en polilíneas suaves
        polylines: List[List[List[float]]] = []
        used = [False] * len(segments)
        tol = 1e-4

        def pts_close(a: Tuple[float, float], b: Tuple[float, float]) -> bool:
            return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol

        for i in range(len(segments)):
            if used[i]:
                continue
            used[i] = True
            chain = [segments[i][0], segments[i][1]]
            extended = True
            while extended:
                extended = False
                for j in range(len(segments)):
                    if used[j]:
                        continue
                    s0, s1 = segments[j]
                    if pts_close(chain[-1], s0):
                        chain.append(s1)
                        used[j] = True
                        extended = True
                    elif pts_close(chain[-1], s1):
                        chain.append(s0)
                        used[j] = True
                        extended = True
                    elif pts_close(chain[0], s1):
                        chain.insert(0, s0)
                        used[j] = True
                        extended = True
                    elif pts_close(chain[0], s0):
                        chain.insert(0, s1)
                        used[j] = True
                        extended = True
            if len(chain) >= 2:
                polylines.append([[pt[0], pt[1]] for pt in chain])

        if polylines:
            contours.append(
                ContourLine(
                    elevation_m=level,
                    is_major=(idx_lvl % 2 == 0),
                    polylines=polylines,
                )
            )

    return contours


def _derive_contour_interval(relief_amp: float) -> float:
    if relief_amp < 2.5:
        return 0.25
    if relief_amp < 8.0:
        return 0.5
    if relief_amp < 25.0:
        return 2.0
    if relief_amp < 80.0:
        return 5.0
    if relief_amp < 250.0:
        return 15.0
    return 40.0


def _derive_landscape_metadata(
    stac_data: Dict[str, Any],
    mean_slope_pct: float,
    max_slope_pct: float,
    relief_amp: float,
    z_min: float,
    z_max: float,
    z_mean: float,
    depression_score: float,
) -> Dict[str, Any]:
    """
    Deriva etiquetas geomorfológicas, sustrato edáfico, red de drenaje y profundidad
    freática estimada a partir EXCLUSIVAMENTE de telemetría real (DEM + WorldCover + JRC + OSM).
    """
    hydro_env = stac_data.get("hydro_env") or {}
    env_type = str(hydro_env.get("environment_type", "rural_agricola"))
    water_dist_m = hydro_env.get("water_distance_m")
    cropland_pct = float(hydro_env.get("cropland_pct", 0.0))
    urban_pct = float(hydro_env.get("urban_pct", 0.0))
    bare_pct = float(hydro_env.get("bare_pct", 0.0))
    wetland_pct = float(hydro_env.get("wetland_pct", 0.0))
    tree_pct = float(hydro_env.get("tree_pct", 0.0))
    grassland_pct = float(hydro_env.get("grassland_pct", 0.0))
    center_is_water = bool(hydro_env.get("center_is_water", False))
    jrc_occ = float(stac_data.get("jrc_occurrence_pct", 0.0))

    contour_interval = _derive_contour_interval(relief_amp)

    if env_type == "oceano_mar_abierto":
        region = "Plataforma Marina / Aguas Abiertas (Cota 0 msnm)"
        soil = "Lecho Marino / Sin Suelo Agronómico (Medio Acuático)"
        drainage = "Dinámica Marina / Mareas y Corrientes Litorales"
        base_wt = 0.0
    elif env_type in ("cuerpo_agua_abierto", "cauce_fluvial_rio"):
        region = "Cauce Activo / Espejo Fluvial o Estuarino"
        soil = "Lecho Hídrico / Sedimentos Subácueos (Sin Perfil Cultivable)"
        drainage = "Corriente Activa / Escurrimiento Encauzado Permanente"
        base_wt = 0.0
    elif env_type == "laguna_cuerpo_agua":
        region = "Cubeta Lacustre / Laguna o Embalse Permanente"
        soil = "Sedimentos Lacustres Hidromórficos (Sumergido)"
        drainage = "Cuenca Endorreica o Lacustre / Almacenamiento Superficial"
        base_wt = 0.0
    elif env_type == "borde_costero_marino":
        if z_max >= 12.0 or mean_slope_pct >= 5.0:
            region = "Frente Costero con Acantilado / Barranca Litoral"
            soil = "Sedimentos Litorales Expuestos / Arenas y Barranca Costera"
        else:
            region = "Faja Costera Litoral / Cordón de Médanos y Playa"
            soil = "Arenas Costeras / Suelos Litorales Salinos o Arenosos"
        drainage = "Desembocadura Litoral / Escorrentía Directa hacia Línea de Costa"
        base_wt = round(max(0.2, min(4.0, z_mean * 0.25)), 2) if not center_is_water else 0.0
    elif env_type == "area_urbana":
        region = f"Área Urbana Consolidada / Tejido Edificado ({urban_pct:.0f}% impermeable)"
        soil = "Sustrato Antrópico / Pavimento e Infraestructura Urbana"
        drainage = "Escorrentía Impermeable / Red de Drenaje Pluvial Urbano"
        base_wt = 0.0 if center_is_water else round(max(1.2, 2.0 + mean_slope_pct * 0.6), 2)
    elif env_type == "humedal_delta":
        region = f"Humedal / Bañado o Planicie Aluvial Inundable ({wetland_pct:.0f}% vegetación palustre)"
        soil = "Complejo Hidromórfico / Fluvisoles y Gleysoles de Bañado"
        drainage = "Planicie Anemófita / Flujo Difuso y Retención Prolongada"
        base_wt = 0.15 if center_is_water else 0.45
    elif env_type == "lote_ribereño_fluvial":
        dist_txt = f"{water_dist_m:.0f} m" if water_dist_m is not None else "cercano"
        region = f"Planicie Aluvial / Terraza Ribereña Fluvial (cauce a {dist_txt})"
        soil = f"Suelos Aluviales Ribereños / Transición Agrícola ({cropland_pct:.0f}% cultivo)"
        drainage = "Drenaje Convergente hacia Cauce Fluvial (Exposición a Crecidas)"
        base_wt = round(max(0.45, min(2.8, 0.7 + relief_amp * 0.06)), 2)
    elif env_type == "relieve_serrano_escarpado":
        if z_mean >= 900.0:
            region = f"Ambiente Montañoso / Relieve Elevado ({z_mean:.0f} msnm)"
        else:
            region = f"Ambiente Serrano / Relieve Estructural Escarpado ({mean_slope_pct:.1f}% pend.)"
        soil = "Suelos Líticos Someros / Roca Aflorante y Regolito Serranos"
        drainage = "Torrencial Dendrítico Encajonado / Rápida Concentración en Quebradas"
        base_wt = round(min(25.0, max(4.5, relief_amp * 0.10)), 2)
    elif env_type == "suelo_desnudo_arenal_roca":
        region = f"Superficie Mineral Desnuda / Arenal, Salar o Roca ({bare_pct:.0f}% sin cobertura)"
        soil = "Sustrato Mineral Sin Cobertura Vegetal (Arena / Salinidad / Lítico)"
        drainage = "Infiltración Rápida en Arena o Escorrentía Directa en Sustrato Duro"
        base_wt = round(max(1.5, 2.5 + mean_slope_pct * 0.7), 2)
    elif env_type == "bosque_monte":
        region = f"Ambiente Boscoso / Monte Nativo o Forestación ({tree_pct:.0f}% cobertura arbórea)"
        soil = "Suelos Forestales con Horizonte Orgánico / Cobertura Arbórea Permanente"
        drainage = "Interceptación Canopia / Escurrimiento Retardado por Cobertura"
        base_wt = round(max(1.2, 1.8 + (1.0 - depression_score) * 2.5 + mean_slope_pct * 0.5), 2)
    else:
        # rural_agricola / pastizal
        if mean_slope_pct < 0.8 and depression_score >= 0.55:
            region = "Planicie Deprimida / Ambiente Hidromórfico de Baja Pendiente"
        elif mean_slope_pct < 1.5:
            region = "Llanura Aluvial / Ondulación Suave"
        elif mean_slope_pct < 4.0:
            region = "Planicie Ondulada / Lomadas Bien Drenadas"
        else:
            region = "Piedemonte / Lomadas Pronunciadas"

        if jrc_occ >= 15.0 or wetland_pct >= 10.0 or depression_score >= 0.65:
            soil = f"Complejo Hidromórfico / Suelos con Limitante de Drenaje ({grassland_pct:.0f}% pastizal)"
        elif cropland_pct >= 45.0 and mean_slope_pct < 2.5:
            soil = f"Suelos Profundos de Uso Agrícola ({cropland_pct:.0f}% cultivo activo WorldCover)"
        elif mean_slope_pct >= 3.0:
            soil = "Suelos Moderadamente Profundos con Susceptibilidad a Erosión Hídrica"
        else:
            soil = f"Suelos Mixtos Agrícolas-Ganaderos ({cropland_pct:.0f}% cultivo, {grassland_pct:.0f}% pastizal)"

        if mean_slope_pct >= 2.5:
            drainage = "Integrado Dendrítico / Buena Evacuación Superficial"
        elif depression_score >= 0.55:
            drainage = "Desorganizado / Baja Pendiente con Encharcamiento Frecuente"
        else:
            drainage = "Dendrítico Moderado / Escurrimiento Superficial Laminar"

        base_wt = round(max(0.7, 1.3 + (1.0 - depression_score) * 3.4 + min(4.0, mean_slope_pct * 0.7)), 2)

    return {
        "region": region,
        "soil_taxonomy": soil,
        "drainage_network": drainage,
        "contour_interval_m": contour_interval,
        "base_water_table_m": base_wt,
    }


def _classify_zones_by_environment(
    env_type: str,
    z_grid: List[List[float]],
    water_mask: List[List[int]],
    z_min: float,
    z_max: float,
    relief_amp: float,
    depression_score: float,
) -> Tuple[List[List[str]], Dict[str, List[float]], List[Tuple[str, str, str, str]]]:
    """
    Segmenta la grilla 17x17 en 4 ambientes geomorfológicos/hídricos reales combinando
    la cota Copernicus DEM y la máscara de agua/humedal (JRC + ESA WorldCover).
    """
    grid_n = len(z_grid)
    zone_grid: List[List[str]] = []
    zone_buckets: Dict[str, List[float]] = {
        "loma_alta": [],
        "media_loma": [],
        "bajo_dulce": [],
        "bajo_inundable": [],
    }

    z_q25 = z_min + relief_amp * 0.24
    z_q50 = z_min + relief_amp * 0.52
    z_q78 = z_min + relief_amp * 0.76

    if depression_score >= 0.7:
        z_q25 = z_min + relief_amp * 0.42
        z_q50 = z_min + relief_amp * 0.68
        z_q78 = z_min + relief_amp * 0.86
    elif env_type == "relieve_serrano_escarpado":
        z_q25 = z_min + relief_amp * 0.14
        z_q50 = z_min + relief_amp * 0.32
        z_q78 = z_min + relief_amp * 0.58
    elif depression_score <= 0.18:
        z_q25 = z_min + relief_amp * 0.10
        z_q50 = z_min + relief_amp * 0.28
        z_q78 = z_min + relief_amp * 0.55

    water_centric = env_type in (
        "oceano_mar_abierto",
        "cuerpo_agua_abierto",
        "cauce_fluvial_rio",
        "laguna_cuerpo_agua",
        "borde_costero_marino",
        "lote_ribereño_fluvial",
        "humedal_delta",
    )

    for r in range(grid_n):
        row_classes: List[str] = []
        for c in range(grid_n):
            zv = z_grid[r][c]
            wm = water_mask[r][c] if r < len(water_mask) and c < len(water_mask[r]) else 0

            if wm == 2:
                zk = "bajo_inundable"
            elif wm == 1 and env_type != "relieve_serrano_escarpado":
                zk = "bajo_dulce"
            elif env_type == "oceano_mar_abierto":
                zk = "bajo_inundable" if zv <= 0.5 else "bajo_dulce"
            elif env_type == "relieve_serrano_escarpado":
                if zv >= z_q78:
                    zk = "bajo_inundable"
                elif zv >= z_q50:
                    zk = "bajo_dulce"
                elif zv >= z_q25:
                    zk = "media_loma"
                else:
                    zk = "loma_alta"
            elif water_centric:
                # Para zonas ribereñas/costeras/humedales, las tierras emergidas se gradúan en loma/media/bajo
                if zv >= z_q78:
                    zk = "loma_alta"
                elif zv >= z_q50:
                    zk = "media_loma"
                else:
                    zk = "bajo_dulce"
            else:
                if zv >= z_q78:
                    zk = "loma_alta"
                elif zv >= z_q50:
                    zk = "media_loma"
                elif zv >= z_q25:
                    zk = "bajo_dulce"
                else:
                    zk = "bajo_inundable"

            row_classes.append(zk)
            zone_buckets[zk].append(zv)
        zone_grid.append(row_classes)

    if env_type == "oceano_mar_abierto":
        zone_meta = [
            ("loma_alta", "Tierra Emergida Marginal", "#10b981", "Eventuales islotes o bordes emergidos en el borde del encuadre."),
            ("media_loma", "Transición Costera", "#38bdf8", "Franja de transición marina-litoral somera."),
            ("bajo_dulce", "Aguas Someras / Rompiente", "#0284c7", "Zona marina somera sin perfil edáfico agrícola."),
            ("bajo_inundable", "Mar Abierto / Aguas Oceánicas", "#0369a1", "Masa oceánica permanente (Cota 0 msnm). Nula aptitud agrícola."),
        ]
    elif env_type in ("cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua"):
        zone_meta = [
            ("loma_alta", "Terraza / Costa Alta Adyacente", "#10b981", "Borde firme elevado fuera del espejo de agua principal."),
            ("media_loma", "Borde Ribereño / Albardón", "#3b82f6", "Margen de transición expuesto a crecidas y erosión lateral."),
            ("bajo_dulce", "Planicie Inundable / Humedal Marginal", "#f59e0b", "Zona palustre o playa inundable en crecidas estacionales."),
            ("bajo_inundable", "Espejo de Agua / Cauce Permanente", "#0284c7", "Cuerpo de agua superficial o lecho activo (JRC + WorldCover 80). No cultivable."),
        ]
    elif env_type == "borde_costero_marino":
        zone_meta = [
            ("loma_alta", "Planicie Alta Interior Post-Costera", "#10b981", "Sector firme retirado del frente marino directo; aptitud sujeta a brisa salina y pendiente."),
            ("media_loma", "Barranca / Cordón Arenoso de Transición", "#3b82f6", "Frente de barranca o duna fija con alta vulnerabilidad erosiva ante viento y escorrentía."),
            ("bajo_dulce", "Franja de Playa / Médano Vivo / Humedal", "#f59e0b", "Arena móvil o bajío salino intermareal; requiere conservación de cordón dunario."),
            ("bajo_inundable", "Frente Marino / Rompiente y Aguas Litorales", "#0284c7", "Espejo marino permanente adyacente a la línea de costa."),
        ]
    elif env_type == "lote_ribereño_fluvial":
        zone_meta = [
            ("loma_alta", "Terraza Alta No Inundable", "#10b981", "Sector elevado alejado del cauce; cultivable según pendiente y cobertura activa."),
            ("media_loma", "Media Loma / Borde Ribereño", "#3b82f6", "Transición hacia el valle fluvial; requiere manejo conservacionista de escorrentía."),
            ("bajo_dulce", "Valle Aluvial / Bañado Ribereño", "#f59e0b", "Planicie de desborde fluvial y vegetación ribereña; conservar franja buffer ≥ 50 m."),
            ("bajo_inundable", "Cauce Fluvial / Brazo de Agua Activo", "#0284c7", "Curso de río o arroyo detectado satelitalmente; exclusión agrícola obligatoria."),
        ]
    elif env_type == "humedal_delta":
        zone_meta = [
            ("loma_alta", "Albardón Emergente / Sector Alto", "#10b981", "Sectores puntuales más altos sobre el plano aluvial."),
            ("media_loma", "Terraza Húmeda de Transición", "#3b82f6", "Suelos saturables en crecidas; aptitud restringida a pasturas tolerantes o forestación."),
            ("bajo_dulce", "Bañado / Vegetación Palustre (Humedal)", "#f59e0b", "Humedal activo (WorldCover 90) con napa somera y alto valor ecosistémico."),
            ("bajo_inundable", "Canales / Lagunas Permanentes", "#0284c7", "Espejos de agua y vías de escurrimiento permanente dentro del humedal."),
        ]
    elif env_type == "area_urbana":
        zone_meta = [
            ("loma_alta", "Sectores Altos Urbanos (Buen Drenaje)", "#3b82f6", "Áreas edificadas sobre cotas superiores con rápido escurrimiento pluvial."),
            ("media_loma", "Tejido Urbano Consolidado", "#64748b", "Superficie impermeabilizada (WorldCover 50); sin uso agronómico."),
            ("bajo_dulce", "Bajos Urbanos / Áreas Deprimidas", "#f59e0b", "Zonas bajas vulnerables a acumulación de excedentes pluviales."),
            ("bajo_inundable", "Vías Hídricas / Zonas de Anegamiento", "#ef4444", "Cota crítica receptora o cauce urbano con riesgo directo de inundación."),
        ]
    elif env_type == "relieve_serrano_escarpado":
        zone_meta = [
            ("loma_alta", "Piedemonte Coluvial / Valle Basal", "#10b981", "Sector basal con mayor acumulación coluvial relativa; apto para pasturas o verdeos en contorno."),
            ("media_loma", "Faldeo Periserrano Tendido", "#3b82f6", "Ladera inferior con contacto lítico somero; uso ganadero extensivo con control de erosión."),
            ("bajo_dulce", "Ladera Escarpada (Riesgo Erosivo Crítico)", "#f59e0b", "Fuerte pendiente con escorrentía rápida y suelo delgado; no apto para laboreo agrícola."),
            ("bajo_inundable", "Cresta / Afloramiento Rocoso / Escarpa", "#ef4444", "Cumbres y laderas extremas sin desarrollo edáfico útil; área de conservación natural."),
        ]
    else:
        zone_meta = [
            ("loma_alta", "Loma Alta Bien Drenada", "#10b981", "Cota superior aireada sin riesgo de anegamiento; máxima estabilidad operativa."),
            ("media_loma", "Media Loma de Transición", "#3b82f6", "Posición intermedia de tránsito hídrico; buen equilibrio humedad-aireación."),
            ("bajo_dulce", "Bajo Tendido / Transición Húmeda", "#f59e0b", "Sector receptor de escorrentía con humedad acumulada; apto para pasturas o cultivos tolerantes."),
            ("bajo_inundable", "Bajo Inundable / Cubeta / Espejo de Agua", "#ef4444", "Depresión receptora con recurrencia hídrica JRC o agua superficial; excluir de agricultura intensiva."),
        ]

    return zone_grid, zone_buckets, zone_meta


def build_topographic_analysis(
    lat: float,
    lon: float,
    stac_data: Dict[str, Any],
    area_ha: float = 100.0,
) -> TopographicAnalysisData:
    """
    Construye el estudio topográfico, geomorfológico, de escurrimiento D8,
    perfiles de corte y zonificación a partir del DEM Copernicus 30m y máscaras reales.
    """
    bbox = stac_data.get("bbox")
    z_grid_raw = stac_data.get("elevation_grid_17")
    hydro_env = stac_data.get("hydro_env") or {}
    env_type = str(hydro_env.get("environment_type", "rural_agricola"))
    water_mask = hydro_env.get("water_mask_grid") or [[0 for _ in range(17)] for _ in range(17)]
    depression_score = float(stac_data.get("relative_depression_score", 0.25))

    grid_n = len(z_grid_raw) if isinstance(z_grid_raw, list) and z_grid_raw else 17

    if isinstance(bbox, list) and len(bbox) == 4:
        min_lon, min_lat, max_lon, max_lat = [float(x) for x in bbox]
    else:
        half_side_km = max(0.85, min(2.5, math.sqrt(max(25.0, area_ha) / 100.0) * 0.9))
        deg_lat = half_side_km / 111.32
        deg_lon = half_side_km / (111.32 * max(0.2, math.cos(math.radians(lat))))
        min_lon, min_lat, max_lon, max_lat = lon - deg_lon, lat - deg_lat, lon + deg_lon, lat + deg_lat

    lats = [
        round(min_lat + (max_lat - min_lat) * (r + 0.5) / grid_n, 6)
        for r in range(grid_n)
    ]
    lons = [
        round(min_lon + (max_lon - min_lon) * (c + 0.5) / grid_n, 6)
        for c in range(grid_n)
    ]

    if isinstance(z_grid_raw, list) and len(z_grid_raw) == grid_n and len(z_grid_raw[0]) == grid_n:
        z_grid = [[round(float(v), 2) for v in row] for row in z_grid_raw]
    else:
        elev = float(stac_data.get("elevation_m", 0.0))
        z_grid = [[round(elev, 2) for _ in range(grid_n)] for _ in range(grid_n)]

    z_flat = [v for row in z_grid for v in row]
    z_min = round(min(z_flat), 2)
    z_max = round(max(z_flat), 2)
    z_mean = round(sum(z_flat) / len(z_flat), 2)
    relief_amp = round(z_max - z_min, 2)

    # Tamaño físico real por celda en metros
    cell_dy_m = max(10.0, ((max_lat - min_lat) / grid_n) * 111320.0)
    cell_dx_m = max(10.0, ((max_lon - min_lon) / grid_n) * 111320.0 * max(0.2, math.cos(math.radians(lat))))
    step_lat_deg = (max_lat - min_lat) / grid_n
    step_lon_deg = (max_lon - min_lon) / grid_n

    # Cálculo de vectores de escurrimiento D8, pendientes reales, TPI y TRI sobre el DEM
    flow_vectors: List[FlowVector] = []
    slopes_pct_list: List[float] = []
    aspect_sin_sum = 0.0
    aspect_cos_sum = 0.0
    tri_diffs: List[float] = []

    inflow_count = [[1 for _ in range(grid_n)] for _ in range(grid_n)]
    cells_sorted = sorted(
        [(z_grid[r][c], r, c) for r in range(grid_n) for c in range(grid_n)],
        reverse=True,
    )
    neighbors_offset = [
        (-1, 0),
        (1, 0),
        (0, -1),
        (0, 1),
        (-1, -1),
        (-1, 1),
        (1, -1),
        (1, 1),
    ]

    for z_val, r, c in cells_sorted:
        best_drop = 0.0
        best_nr, best_nc = -1, -1
        for dr, dc in neighbors_offset:
            nr, nc = r + dr, c + dc
            if 0 <= nr < grid_n and 0 <= nc < grid_n:
                dist = math.hypot(dr * cell_dy_m, dc * cell_dx_m)
                drop = (z_val - z_grid[nr][nc]) / dist
                if drop > best_drop:
                    best_drop = drop
                    best_nr, best_nc = nr, nc
        if best_nr != -1:
            inflow_count[best_nr][best_nc] += inflow_count[r][c]

    for r in range(1, grid_n - 1):
        for c in range(1, grid_n - 1):
            dz_dx = (z_grid[r][c + 1] - z_grid[r][c - 1]) / (2.0 * cell_dx_m)
            dz_dy = (z_grid[r + 1][c] - z_grid[r - 1][c]) / (2.0 * cell_dy_m)

            grad_mag = math.hypot(dz_dx, dz_dy)
            local_slope_pct = grad_mag * 100.0
            slopes_pct_list.append(local_slope_pct)

            nb_vals = [z_grid[r + dr][c + dc] for dr, dc in neighbors_offset]
            tri_diffs.append(
                math.sqrt(sum((z_grid[r][c] - nv) ** 2 for nv in nb_vals) / 8.0)
            )

            fx, fy = -dz_dx, -dz_dy
            if grad_mag > 1e-5:
                azimuth = (math.degrees(math.atan2(fx, fy)) + 360.0) % 360.0
                aspect_sin_sum += math.sin(math.radians(azimuth))
                aspect_cos_sum += math.cos(math.radians(azimuth))
            else:
                azimuth = 135.0

            if r % 2 == 1 and c % 2 == 1:
                # En celdas de agua abierta plana omitimos flechas espurias si el gradiente es nulo
                wm = water_mask[r][c] if r < len(water_mask) and c < len(water_mask[r]) else 0
                if wm == 2 and local_slope_pct < 0.05:
                    continue
                vec_scale = 0.85
                ux = math.sin(math.radians(azimuth))
                uy = math.cos(math.radians(azimuth))
                dlat_arrow = step_lat_deg * 1.35 * uy * vec_scale
                dlon_arrow = step_lon_deg * 1.35 * ux * vec_scale

                acc_cells = inflow_count[r][c]
                is_concentration = acc_cells >= 6 or (
                    relief_amp > 0.2 and z_grid[r][c] < (z_min + relief_amp * 0.28)
                )

                flow_vectors.append(
                    FlowVector(
                        lat=lats[r],
                        lon=lons[c],
                        target_lat=round(lats[r] + dlat_arrow, 6),
                        target_lon=round(lons[c] + dlon_arrow, 6),
                        azimuth_deg=round(azimuth, 1),
                        slope_pct=round(local_slope_pct, 2),
                        flow_accumulation=acc_cells,
                        is_drainage_channel=is_concentration,
                    )
                )

    mean_slope_pct = round(
        sum(slopes_pct_list) / max(1, len(slopes_pct_list)), 2
    )
    max_slope_pct = round(max(slopes_pct_list) if slopes_pct_list else 0.0, 2)
    tri_mean = round(sum(tri_diffs) / max(1, len(tri_diffs)), 2)
    real_slope_deg = math.degrees(math.atan(mean_slope_pct / 100.0))

    if abs(aspect_sin_sum) < 1e-9 and abs(aspect_cos_sum) < 1e-9:
        mean_aspect_deg = 0.0
    else:
        mean_aspect_deg = round(
            (math.degrees(math.atan2(aspect_sin_sum, aspect_cos_sum)) + 360.0) % 360.0, 1
        )
    aspect_cardinal = _cardinal_from_azimuth(mean_aspect_deg, mean_slope_pct)

    reg_info = _derive_landscape_metadata(
        stac_data=stac_data,
        mean_slope_pct=mean_slope_pct,
        max_slope_pct=max_slope_pct,
        relief_amp=relief_amp,
        z_min=z_min,
        z_max=z_max,
        z_mean=z_mean,
        depression_score=depression_score,
    )
    base_wt = reg_info["base_water_table_m"]
    water_table_base_msnm = z_mean - base_wt

    contours = _marching_squares_contours(
        lats, lons, z_grid, interval=reg_info["contour_interval_m"]
    )

    center_z = z_grid[grid_n // 2][grid_n // 2]
    tpi_val = round(center_z - z_mean, 2)
    tpi_norm = tpi_val / max(0.35, relief_amp * 0.5)
    is_water_body = env_type in ("oceano_mar_abierto", "cuerpo_agua_abierto", "cauce_fluvial_rio", "laguna_cuerpo_agua")
    is_steep_serrano = env_type == "relieve_serrano_escarpado"

    if is_water_body:
        tpi_label = "Espejo Hídrico / Superficie Hidrostática Base"
    elif is_steep_serrano:
        if tpi_norm > 0.25:
            tpi_label = "Cumbre / Cresta rocosa de alta pendiente"
        elif tpi_norm > -0.30:
            tpi_label = "Ladera serrana escarpada / Escorrentía torrencial"
        else:
            tpi_label = "Quebrada / Valle interserrano colector"
    elif tpi_norm > 0.35:
        tpi_label = "Loma convexa / Posición emisora de agua"
    elif tpi_norm > -0.25:
        tpi_label = "Media loma / Plano de tránsito hídrico"
    elif tpi_norm > -0.65:
        tpi_label = "Bajo tendido / Posición receptora"
    else:
        tpi_label = "Cubeta cóncava / Depresión de acumulación"

    center_acc = inflow_count[grid_n // 2][grid_n // 2]
    specific_catchment_m = max(30.0, center_acc * cell_dx_m * (1.0 + depression_score * 3.5))
    tan_beta = max(0.0004, math.tan(math.radians(max(0.02, real_slope_deg))))
    twi_val = round(math.log(specific_catchment_m / tan_beta), 2)

    if is_water_body:
        twi_label = "Cuerpo de Agua Superficial · Inundación permanente (cauce / espejo)"
    elif twi_val >= 12.5:
        twi_label = "Muy Alto (>12.5) · Propensión severa a saturación y anegamiento"
    elif twi_val >= 10.0:
        twi_label = "Moderado-Alto (10–12.5) · Acumulación temporal en lluvias intensas"
    elif twi_val >= 8.0:
        twi_label = "Óptimo (8–10) · Buena retención de humedad edáfica sin asfixia radicular"
    else:
        twi_label = "Bajo (<8.0) · Escurrimiento rápido, sin retención superficial"

    slope_length_m = 120.0
    m_exp = 0.5 if mean_slope_pct >= 3.0 else (0.4 if mean_slope_pct >= 1.0 else 0.25)
    theta_rad = math.atan(mean_slope_pct / 100.0)
    ls_factor = round(
        ((slope_length_m / 22.13) ** m_exp)
        * (65.41 * (math.sin(theta_rad) ** 2) + 4.56 * math.sin(theta_rad) + 0.065),
        2,
    )

    if is_water_body:
        erosion_label = "No Aplica / Medio Acuático (Dinámica fluvial o marina)"
    elif env_type == "area_urbana":
        erosion_label = "Superficie Antrópica Impermeable (Riesgo de escorrentía pluvial concentrada)"
    elif is_steep_serrano or ls_factor >= 2.5 or mean_slope_pct >= 7.0:
        erosion_label = "Crítico / Muy Alto (Pendiente escarpada y suelo somero; no arable)"
    elif ls_factor >= 1.2 or mean_slope_pct >= 2.5:
        erosion_label = "Alto (Riesgo de erosión hídrica; requiere terrazas/curvas de nivel)"
    elif ls_factor >= 0.35 or mean_slope_pct >= 0.8:
        erosion_label = "Moderado (Susceptible a escorrentía en barbechos desnudos; exige cobertura)"
    else:
        erosion_label = "Bajo / Nulo (Predomina sedimentación e hidromorfismo sobre erosión)"

    zone_Grid, zone_buckets, zone_meta = _classify_zones_by_environment(
        env_type=env_type,
        z_grid=z_grid,
        water_mask=water_mask,
        z_min=z_min,
        z_max=z_max,
        relief_amp=relief_amp,
        depression_score=depression_score,
    )

    total_cells = float(grid_n * grid_n)
    terrain_zones: List[TerrainZoneStat] = []
    for zk, zlabel, zcolor, zdesc in zone_meta:
        vals = zone_buckets[zk]
        pct = round((len(vals) / total_cells) * 100.0, 1)
        ha_est = round((pct / 100.0) * area_ha, 1)
        mean_z_zone = round(sum(vals) / len(vals), 2) if vals else z_mean
        terrain_zones.append(
            TerrainZoneStat(
                zone_id=zk,
                zone_name=zlabel,
                percentage=pct,
                area_ha=ha_est,
                mean_elevation_m=mean_z_zone,
                color_hex=zcolor,
                agronomic_use=zdesc,
            )
        )

    def _build_profile_from_indices(
        profile_id: str,
        title: str,
        coords_rc: List[Tuple[int, int]],
    ) -> ElevationProfile:
        pts: List[ProfilePoint] = []
        cum_dist = 0.0
        prev_lat, prev_lon, prev_z = None, None, None
        max_local_s = 0.0

        for r, c in coords_rc:
            plat = lats[r]
            plon = lons[c]
            pz = z_grid[r][c]
            pzone = zone_Grid[r][c]
            wm_pt = water_mask[r][c] if r < len(water_mask) and c < len(water_mask[r]) else 0
            if base_wt <= 0.0 or wm_pt == 2:
                wt_msnm = round(pz, 2)
                wt_depth = 0.0
            else:
                wt_msnm = round(water_table_base_msnm + (pz - z_mean) * 0.35, 2)
                wt_depth = round(max(0.0, pz - wt_msnm), 2)

            if prev_lat is not None and prev_lon is not None and prev_z is not None:
                d_m = math.hypot(
                    (plat - prev_lat) * 111320.0,
                    (plon - prev_lon) * 111320.0 * max(0.2, math.cos(math.radians(lat))),
                )
                cum_dist += d_m
                local_s = round(abs(pz - prev_z) / max(1.0, d_m) * 100.0, 2)
                max_local_s = max(max_local_s, local_s)
            else:
                local_s = 0.0

            pts.append(
                ProfilePoint(
                    distance_m=round(cum_dist, 1),
                    lat=plat,
                    lon=plon,
                    elevation_m=pz,
                    water_table_msnm=wt_msnm,
                    water_table_depth_m=wt_depth,
                    slope_local_pct=local_s,
                    zone_id=pzone,
                )
            )
            prev_lat, prev_lon, prev_z = plat, plon, pz

        p_elevs = [p.elevation_m for p in pts]
        p_min = min(p_elevs)
        p_max = max(p_elevs)
        avg_s = round(((p_max - p_min) / max(1.0, cum_dist)) * 100.0, 2)

        return ElevationProfile(
            profile_id=profile_id,
            title=title,
            total_distance_m=round(cum_dist, 1),
            min_elevation_m=p_min,
            max_elevation_m=p_max,
            relief_delta_m=round(p_max - p_min, 2),
            avg_slope_pct=avg_s,
            max_slope_pct=round(max_local_s, 2),
            points=pts,
        )

    mid = grid_n // 2
    ns_rc = [(grid_n - 1 - i, mid) for i in range(grid_n)]
    we_rc = [(mid, i) for i in range(grid_n)]
    diag_rc = [(grid_n - 1 - i, i) for i in range(grid_n)]

    profiles = [
        _build_profile_from_indices("north_south", "Transecta Norte → Sur (N-S)", ns_rc),
        _build_profile_from_indices("west_east", "Transecta Oeste → Este (O-E)", we_rc),
        _build_profile_from_indices(
            "drainage_axis", "Transecta Diagonal NO → SE (Eje de Escurrimiento)", diag_rc
        ),
    ]

    est_wt_center = 0.0 if (base_wt <= 0.0 or (water_mask[mid][mid] == 2)) else round(
        max(0.15, base_wt + (center_z - z_mean) * 0.4), 2
    )

    geomorphology = GeomorphologyMetrics(
        region_geomorphology=reg_info["region"],
        soil_taxonomy_inta=reg_info["soil_taxonomy"],
        drainage_network_type=reg_info["drainage_network"],
        slope_pct=mean_slope_pct,
        max_slope_pct=max_slope_pct,
        min_elevation_m=z_min,
        max_elevation_m=z_max,
        relief_amplitude_m=relief_amp,
        contour_interval_m=reg_info["contour_interval_m"],
        twi_value=twi_val,
        twi_label=twi_label,
        tpi_value_m=tpi_val,
        tpi_label=tpi_label,
        tri_rugosity_m=tri_mean,
        aspect_deg=mean_aspect_deg,
        aspect_cardinal=aspect_cardinal,
        ls_erosion_factor=ls_factor,
        erosion_risk_label=erosion_label,
        estimated_water_table_depth_m=est_wt_center,
    )

    geodesy_info = compute_geodetic_summary(lat, lon, elevation_m=center_z)

    return TopographicAnalysisData(
        grid_lats=lats,
        grid_lons=lons,
        elevation_grid=z_grid,
        zone_grid=zone_Grid,
        water_table_base_msnm=round(water_table_base_msnm, 2),
        geomorphology=geomorphology,
        terrain_zones=terrain_zones,
        contours=contours,
        flow_vectors=flow_vectors,
        elevation_profiles=profiles,
        geodesy=geodesy_info,
    )
