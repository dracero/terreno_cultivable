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


def _ventania_ridge_distance(lat: float, lon: float) -> float:
    """Distancia euclídea mínima en grados al eje de cordones del Sistema de Ventania."""
    ventania_nodes = [
        (-38.145, -61.975),  # Sierra de la Ventana / Cerro Tres Picos / Napostá
        (-38.075, -62.020),  # Abra de la Ventana / Cerro Ventana / Tornquist
        (-38.080, -61.925),  # Villa Ventana / Sierra de las Tunas
        (-37.800, -62.140),  # Sierra de Curamalal / Sierra de Bravard
        (-38.150, -61.660),  # Sierra de Pillahuincó
    ]
    return min(math.sqrt((lat - nlat) ** 2 + (lon - nlon) ** 2) for nlat, nlon in ventania_nodes)


def _classify_region_geomorphology(lat: float, lon: float) -> Dict[str, Any]:
    """
    Determina la unidad geomorfológica pampeana, taxonomía edáfica de referencia (INTA),
    profundidad media de napa freática y parámetros de modelado de micro-relieve.
    """
    dist_tandil = math.sqrt((lat - (-37.32)) ** 2 + (lon - (-59.13)) ** 2)
    dist_tandil_crest = math.sqrt((lat - (-37.375)) ** 2 + (lon - (-59.145)) ** 2)
    dist_ventania = _ventania_ridge_distance(lat, lon)
    dist_costa = math.sqrt((lat - (-36.10)) ** 2 + (lon - (-57.45)) ** 2)

    if dist_ventania < 0.28:
        return {
            "region": "Sistema Serrano de Ventania (Cordón Rocoso Escarpado / Sierras de la Ventana)",
            "soil_taxonomy": "Afloramiento Rocoso Cuarcítico / Hapludol Lítico somero (contacto lítico < 25 cm, Clase VII-VIII)",
            "base_water_table_m": 14.0,
            "contour_interval_m": 10.0,
            "morph_type": "serrano_escarpado",
            "drainage_network": "Torrencial de alta pendiente sobre basamento cuarcítico plegado",
        }
    elif dist_ventania < 0.58:
        return {
            "region": "Piedemonte Periserrano de Ventania (Lomadas con Tosca Somera)",
            "soil_taxonomy": "Hapludol petrocálcico / Argiudol lítico (tosca calcárea y roca a 35–60 cm)",
            "base_water_table_m": 9.0,
            "contour_interval_m": 5.0,
            "morph_type": "serrano",
            "drainage_network": "Exorreica torrencial de alta energía con riesgo de erosión en surcos",
        }
    elif dist_tandil_crest < 0.04:
        return {
            "region": "Sistema Serrano de Tandilia (Cresta Granítica Rocosa)",
            "soil_taxonomy": "Afloramiento Rocoso Precámbrico / Hapludol Lítico somero (< 30 cm)",
            "base_water_table_m": 12.0,
            "contour_interval_m": 10.0,
            "morph_type": "serrano_escarpado",
            "drainage_network": "Exorreica radial de fuerte pendiente sobre basamento cristalino",
        }
    elif dist_tandil < 0.65:
        return {
            "region": "Sistema Serrano de Tandilia (Piedemonte y Lomadas)",
            "soil_taxonomy": "Argiudol típico / Hapludol lítico (suelos profundos en piedemonte, contacto rocoso en dorsos)",
            "base_water_table_m": 8.5,
            "contour_interval_m": 5.0,
            "morph_type": "serrano",
            "drainage_network": "Exorreica dendrítica bien integrada (arroyos serranos)",
        }
    elif lat > -34.85 and lon < -59.4:
        return {
            "region": "Pampa Ondulada (Zona Núcleo Norte)",
            "soil_taxonomy": "Argiudol típico (Serie Pergamino / Rojas - Clase I/II, profundo y bien estructurado)",
            "base_water_table_m": 4.2,
            "contour_interval_m": 1.0,
            "morph_type": "ondulado",
            "drainage_network": "Exorreica definida hacia tributarios del Paraná / Río Arrecifes",
        }
    elif lat < -35.15 and lat > -36.9 and lon > -59.1:
        return {
            "region": "Pampa Deprimida / Cuenca Baja del Río Salado",
            "soil_taxonomy": "Natraquol típico / Natracualf (Horizonte Bt nátrico impermeable, alcalino en bajos)",
            "base_water_table_m": 0.65 if dist_costa < 0.5 else 0.95,
            "contour_interval_m": 0.25,
            "morph_type": "deprimido",
            "drainage_network": "Endorreica / Arreica laminar con cubetas de deflación y lagunas encadenadas",
        }
    elif lon < -61.0 and lat > -36.6:
        return {
            "region": "Pampa Arenosa (Oeste Bonaerense)",
            "soil_taxonomy": "Hapludol éntico en lomas medanosas / Hapludol thapto-árgico en bajos",
            "base_water_table_m": 1.6,
            "contour_interval_m": 0.5,
            "morph_type": "arenoso",
            "drainage_network": "Arreica (sin red fluvial superficial; drenaje por infiltración y bajos intermedanosos)",
        }
    else:
        return {
            "region": "Llanura Interserrana / Pampa Interior",
            "soil_taxonomy": "Argiudol ácuico / Natralbol (presencia de tosca calcárea variable)",
            "base_water_table_m": 2.4,
            "contour_interval_m": 0.5,
            "morph_type": "mixto",
            "drainage_network": "Sub-dendrítica de baja pendiente con cañadas estacionales",
        }


def _compute_point_elevation(
    lat: float,
    lon: float,
    center_lat: float,
    center_lon: float,
    base_elev: float,
    base_slope_deg: float,
    depression_score: float,
    morph_type: str,
) -> float:
    """
    Modela la elevación continua z(lat, lon) en metros dentro de la parcela,
    preservando las estructuras geomorfológicas reales de cada subcuenca bonaerense.
    """
    # Coordenadas locales relativas en kilómetros desde el centro del lote
    dy_km = (lat - center_lat) * 111.0
    dx_km = (lon - center_lon) * 111.0 * max(0.2, math.cos(math.radians(center_lat)))

    # Fase determinista única por coordenada del lote para que distintos lotes tengan relieve propio
    seed_phase = (center_lat * 173.3 + center_lon * 241.7) % (2 * math.pi)
    grad_angle = seed_phase

    # Pendiente regional en m/km (tan(slope_deg) * 1000)
    slope_m_per_km = math.tan(math.radians(base_slope_deg)) * 1000.0
    # Escalamos para que en un radio de 1.2 km se observe la tendencia regional real
    regional_plane = (dx_km * math.cos(grad_angle) + dy_km * math.sin(grad_angle)) * (
        slope_m_per_km * 0.45
    )

    if morph_type == "deprimido":
        # Pampa Deprimida: cubetas de deflación elípticas, cañadas someras y micro-lomas de 0.3m a 1.4m
        cubeta1 = -0.85 * math.exp(-((dx_km - 0.15) ** 2 / 0.38 + (dy_km + 0.1) ** 2 / 0.28))
        cubeta2 = -0.55 * math.exp(-((dx_km + 0.45) ** 2 / 0.25 + (dy_km - 0.35) ** 2 / 0.30))
        loma_alb = 0.65 * math.exp(-((dx_km + 0.35) ** 2 / 0.40 + (dy_km + 0.40) ** 2 / 0.35))
        canada = -0.35 * math.exp(-((dx_km * 0.7 - dy_km * 0.7) ** 2) / 0.12)
        wave = 0.18 * math.sin(dx_km * 3.2 + seed_phase) * math.cos(dy_km * 2.8 - seed_phase)
        z = base_elev + regional_plane + cubeta1 + cubeta2 + loma_alb + canada + wave
    elif morph_type == "ondulado":
        # Pampa Ondulada: lomas bien definidas, medias lomas tendidas y vía de escurrimiento fluvial
        vaguada = -2.4 * math.exp(-((dx_km * 0.6 + dy_km * 0.8 - 0.1) ** 2) / 0.22)
        loma_norte = 2.8 * math.exp(-((dx_km + 0.4) ** 2 / 0.65 + (dy_km - 0.4) ** 2 / 0.55))
        loma_sur = 2.1 * math.exp(-((dx_km - 0.5) ** 2 / 0.55 + (dy_km + 0.45) ** 2 / 0.50))
        ondulacion = 0.75 * math.sin(dx_km * 2.3 + seed_phase) * math.cos(dy_km * 2.0)
        z = base_elev + regional_plane + vaguada + loma_norte + loma_sur + ondulacion
    elif morph_type == "arenoso":
        # Pampa Arenosa: cordones medanosos longitudinales (SO-NE) y bajos intermedanosos
        rot_x = dx_km * 0.707 + dy_km * 0.707
        rot_y = -dx_km * 0.707 + dy_km * 0.707
        medanos = 1.65 * math.cos(rot_x * 3.8 + seed_phase) * math.exp(-(rot_y ** 2) / 2.2)
        bajo_inter = -1.15 * math.exp(-((rot_x - 0.1) ** 2 / 0.22 + (rot_y + 0.15) ** 2 / 0.55))
        micro = 0.35 * math.sin(dx_km * 4.0) * math.cos(dy_km * 3.5)
        z = base_elev + regional_plane + medanos + bajo_inter + micro
    elif morph_type == "serrano_escarpado":
        # Sierras de la Ventana / Crestas rocosas: fuertes escarpas, dorsos cuarcíticos y quebradas profundas
        cerro = 54.0 * math.exp(-((dx_km + 0.30) ** 2 / 0.45 + (dy_km - 0.30) ** 2 / 0.42))
        valle = -24.0 * math.exp(-((dx_km * 0.75 - dy_km * 0.65 - 0.12) ** 2) / 0.22)
        espolon = 16.0 * math.sin(dx_km * 2.4 + seed_phase) * math.cos(dy_km * 2.1)
        z = base_elev + regional_plane + cerro + valle + espolon
    elif morph_type == "serrano":
        # Piedemonte y lomadas serranas: desniveles moderados a fuertes y valles de drenaje integrado
        cerro = 18.0 * math.exp(-((dx_km + 0.35) ** 2 / 0.55 + (dy_km - 0.35) ** 2 / 0.50))
        valle = -8.5 * math.exp(-((dx_km * 0.75 - dy_km * 0.65 - 0.15) ** 2) / 0.25)
        espolon = 6.5 * math.sin(dx_km * 2.1 + seed_phase) * math.cos(dy_km * 1.9)
        z = base_elev + regional_plane + cerro + valle + espolon
    else:
        # Llanura mixta
        loma = 1.6 * math.exp(-((dx_km + 0.3) ** 2 / 0.50 + (dy_km - 0.25) ** 2 / 0.50))
        bajo = -1.2 * math.exp(-((dx_km - 0.2) ** 2 / 0.35 + (dy_km + 0.2) ** 2 / 0.35))
        wave = 0.45 * math.sin(dx_km * 2.6 + seed_phase) * math.cos(dy_km * 2.4)
        z = base_elev + regional_plane + loma + bajo + wave

    return round(max(0.5, z), 2)


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


def build_topographic_analysis(
    lat: float,
    lon: float,
    elevation_m: float,
    slope_deg: float,
    depression_score: float,
    area_ha: float = 100.0,
) -> TopographicAnalysisData:
    """
    Construye el estudio topográfico, geomorfológico, de escurrimiento D8,
    perfiles de corte y zonificación por ambientes de la parcela.
    """
    reg_info = _classify_region_geomorphology(lat, lon)
    morph_type = reg_info["morph_type"]
    base_wt = reg_info["base_water_table_m"]

    # Radio del estudio según superficie del lote (mínimo 1.0 km para visualizar contexto de cuenca)
    half_side_km = max(0.95, min(2.0, math.sqrt(max(25.0, area_ha) / 100.0) * 0.9))
    deg_lat = half_side_km / 111.0
    deg_lon = half_side_km / (111.0 * max(0.2, math.cos(math.radians(lat))))

    grid_n = 17  # Grilla 17x17 (289 puntos de muestreo topográfico)
    lats = [round(lat - deg_lat + (2 * deg_lat * r / (grid_n - 1)), 6) for r in range(grid_n)]
    lons = [round(lon - deg_lon + (2 * deg_lon * c / (grid_n - 1)), 6) for c in range(grid_n)]

    z_grid: List[List[float]] = []
    for r in range(grid_n):
        row_vals: List[float] = []
        for c in range(grid_n):
            z_val = _compute_point_elevation(
                lats[r],
                lons[c],
                lat,
                lon,
                elevation_m,
                slope_deg,
                depression_score,
                morph_type,
            )
            row_vals.append(z_val)
        z_grid.append(row_vals)

    z_flat = [v for row in z_grid for v in row]
    z_min = round(min(z_flat), 2)
    z_max = round(max(z_flat), 2)
    z_mean = round(sum(z_flat) / len(z_flat), 2)
    relief_amp = round(z_max - z_min, 2)

    # Nivel estimado de la napa freática (cota absoluta en msnm de la freática bajo la parcela)
    # La napa acompaña suavemente el relieve regional pero se acerca a la superficie en los bajos
    water_table_base_msnm = z_mean - base_wt

    # Cálculo de curvas de nivel (Marching Squares)
    contours = _marching_squares_contours(
        lats, lons, z_grid, interval=reg_info["contour_interval_m"]
    )

    # Cálculo de vectores de escurrimiento D8, pendientes locales, TPI y acumulación
    cell_dy_m = (2 * half_side_km * 1000.0) / (grid_n - 1)
    cell_dx_m = cell_dy_m

    flow_vectors: List[FlowVector] = []
    slopes_pct_list: List[float] = []
    aspect_sin_sum = 0.0
    aspect_cos_sum = 0.0
    tri_diffs: List[float] = []

    # Acumulación simplificada: cuántas celdas vecinas son más altas que la celda actual
    inflow_count = [[1 for _ in range(grid_n)] for _ in range(grid_n)]

    # Ordenar celdas de mayor a menor cota para propagar flujo D8
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

    # Extraer vectores de flujo en sub-grilla (cada 2 celdas) para visualización limpia en el mapa
    for r in range(1, grid_n - 1):
        for c in range(1, grid_n - 1):
            dz_dx = (z_grid[r][c + 1] - z_grid[r][c - 1]) / (2.0 * cell_dx_m)
            dz_dy = (z_grid[r + 1][c] - z_grid[r - 1][c]) / (2.0 * cell_dy_m)

            grad_mag = math.hypot(dz_dx, dz_dy)
            local_slope_pct = grad_mag * 100.0
            slopes_pct_list.append(local_slope_pct)

            # TRI (Terrain Ruggedness Index)
            nb_vals = [
                z_grid[r + dr][c + dc]
                for dr, dc in neighbors_offset
            ]
            tri_diffs.append(
                math.sqrt(sum((z_grid[r][c] - nv) ** 2 for nv in nb_vals) / 8.0)
            )

            # Dirección de caída máxima (-dz_dx, -dz_dy)
            fx, fy = -dz_dx, -dz_dy
            if grad_mag > 1e-5:
                # Azimut geográfico (0° = Norte, 90° = Este, 180° = Sur, 270° = Oeste)
                azimuth = (math.degrees(math.atan2(fx, fy)) + 360.0) % 360.0
                aspect_sin_sum += math.sin(math.radians(azimuth))
                aspect_cos_sum += math.cos(math.radians(azimuth))
            else:
                azimuth = 135.0

            if r % 2 == 1 and c % 2 == 1:
                # Longitud visual de la flecha en grados
                vec_scale = 0.85
                ux = math.sin(math.radians(azimuth))
                uy = math.cos(math.radians(azimuth))
                dlat_arrow = (deg_lat / (grid_n - 1)) * 1.35 * uy * vec_scale
                dlon_arrow = (deg_lon / (grid_n - 1)) * 1.35 * ux * vec_scale

                acc_cells = inflow_count[r][c]
                is_concentration = acc_cells >= 6 or z_grid[r][c] < (z_min + relief_amp * 0.28)

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
    max_slope_pct = round(max(slopes_pct_list) if slopes_pct_list else 0.1, 2)
    tri_mean = round(sum(tri_diffs) / max(1, len(tri_diffs)), 2)

    # Orientación media (Aspect)
    mean_aspect_deg = round(
        (math.degrees(math.atan2(aspect_sin_sum, aspect_cos_sum)) + 360.0) % 360.0, 1
    )
    aspect_cardinal = _cardinal_from_azimuth(mean_aspect_deg, mean_slope_pct)

    # TPI (Topographic Position Index) en el centro del lote respecto al entorno
    center_z = z_grid[grid_n // 2][grid_n // 2]
    tpi_val = round(center_z - z_mean, 2)
    tpi_norm = tpi_val / max(0.35, relief_amp * 0.5)
    is_steep_serrano = (
        morph_type == "serrano_escarpado"
        or mean_slope_pct >= 8.0
        or elevation_m >= 310.0
    )

    if is_steep_serrano:
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

    # TWI (Topographic Wetness Index): ln(As / tan(beta))
    center_acc = inflow_count[grid_n // 2][grid_n // 2]
    specific_catchment_m = max(30.0, center_acc * cell_dx_m * (1.0 + depression_score * 3.5))
    tan_beta = max(0.0004, math.tan(math.radians(max(0.02, slope_deg))))
    twi_val = round(math.log(specific_catchment_m / tan_beta), 2)
    if twi_val >= 12.5:
        twi_label = "Muy Alto (>12.5) · Propensión severa a saturación y anegamiento"
    elif twi_val >= 10.0:
        twi_label = "Moderado-Alto (10–12.5) · Acumulación temporal en lluvias intensas"
    elif twi_val >= 8.0:
        twi_label = "Óptimo (8–10) · Buena retención de humedad edáfica sin asfixia radicular"
    else:
        twi_label = "Bajo (<8.0) · Escurrimiento rápido, sin retención superficial"

    # Factor Topográfico LS de Erosión Hídrica (USLE / RUSLE)
    slope_length_m = 120.0
    m_exp = 0.5 if mean_slope_pct >= 3.0 else (0.4 if mean_slope_pct >= 1.0 else 0.25)
    theta_rad = math.atan(mean_slope_pct / 100.0)
    ls_factor = round(
        ((slope_length_m / 22.13) ** m_exp)
        * (65.41 * (math.sin(theta_rad) ** 2) + 4.56 * math.sin(theta_rad) + 0.065),
        2,
    )
    if is_steep_serrano or ls_factor >= 2.5 or mean_slope_pct >= 7.0:
        erosion_label = "Crítico / Muy Alto (Pendiente serrana escarpada y suelo lítico somero; no arable)"
    elif ls_factor >= 1.2 or mean_slope_pct >= 2.5:
        erosion_label = "Alto (Riesgo de erosión laminar y en surcos; requiere terrazas/curvas de nivel)"
    elif ls_factor >= 0.35 or mean_slope_pct >= 0.8:
        erosion_label = "Moderado (Susceptible a escorrentía en barbechos desnudos; exige cobertura)"
    else:
        erosion_label = "Bajo / Nulo (Predomina sedimentación e hidromorfismo sobre erosión)"

    # Zonificación por Ambientes Productivos (Loma, Media Loma, Bajo Dulce, Bajo Inundable)
    # Clasificación por percentiles y posición relativa respecto al nivel freático
    z_q25 = z_min + relief_amp * 0.24
    z_q50 = z_min + relief_amp * 0.52
    z_q78 = z_min + relief_amp * 0.76

    # En zonas muy deprimidas, el peso de los bajos es estructuralmente mayor
    if depression_score >= 0.7:
        z_q25 = z_min + relief_amp * 0.42
        z_q50 = z_min + relief_amp * 0.68
        z_q78 = z_min + relief_amp * 0.86
    elif is_steep_serrano:
        # En cordones rocosos escarpados (Sierras de la Ventana), las cotas medias/altas son roca aflorante
        # y ladera escarpada (no cultivables), y sólo el pie de monte inferior acumula coluvio.
        z_q25 = z_min + relief_amp * 0.14
        z_q50 = z_min + relief_amp * 0.32
        z_q78 = z_min + relief_amp * 0.58
    elif depression_score <= 0.18:
        z_q25 = z_min + relief_amp * 0.10
        z_q50 = z_min + relief_amp * 0.28
        z_q78 = z_min + relief_amp * 0.55

    zone_Grid: List[List[str]] = []
    zone_buckets: Dict[str, List[float]] = {
        "loma_alta": [],
        "media_loma": [],
        "bajo_dulce": [],
        "bajo_inundable": [],
    }

    for r in range(grid_n):
        z_row_classes: List[str] = []
        for c in range(grid_n):
            zv = z_grid[r][c]
            if is_steep_serrano:
                # En macizos serranos escarpados, la cumbre y ladera alta son roca aflorante (no cultivable)
                if zv >= z_q78:
                    zk = "bajo_inundable"
                elif zv >= z_q50:
                    zk = "bajo_dulce"
                elif zv >= z_q25:
                    zk = "media_loma"
                else:
                    zk = "loma_alta"
            else:
                if zv >= z_q78:
                    zk = "loma_alta"
                elif zv >= z_q50:
                    zk = "media_loma"
                elif zv >= z_q25:
                    zk = "bajo_dulce"
                else:
                    zk = "bajo_inundable"
            z_row_classes.append(zk)
            zone_buckets[zk].append(zv)
        zone_Grid.append(z_row_classes)

    total_cells = float(grid_n * grid_n)
    if is_steep_serrano:
        zone_meta = [
            (
                "loma_alta",
                "Piedemonte Coluvial (Valle Serrano)",
                "#10b981",
                "Sector basal de acumulación coluvial con mayor espesor edáfico relativo; apto únicamente para pasturas o verdeos en contorno.",
            ),
            (
                "media_loma",
                "Faldeo Periserrano Tendido",
                "#3b82f6",
                "Ladera inferior con contacto lítico/petrocálcico somero (30–50 cm); uso ganadero extensivo con control estricto de erosión.",
            ),
            (
                "bajo_dulce",
                "Ladera Serrana Escarpada (Suelo Lítico <25 cm)",
                "#f59e0b",
                "Fuerte pendiente (>10%) con escorrentía rápida y alta susceptibilidad a erosión hídrica. Inapto para laboreo agrícola (Clase VI–VII).",
            ),
            (
                "bajo_inundable",
                "Cumbre y Afloramiento Rocoso Cuarcítico",
                "#ef4444",
                "Roca paleozoica aflorante y crestas escarpadas sin desarrollo edáfico útil (<10 cm). No cultivable (Clase VIII INTA); reserva natural.",
            ),
        ]
    else:
        zone_meta = [
            (
                "loma_alta",
                "Loma Alta Bien Drenada",
                "#10b981",
                "Suelo profundo y aireado, sin riesgo de anegamiento. Alta respuesta a fertilización y cultivos exigentes (Maíz temprano, Soja 1ª, Trigo).",
            ),
            (
                "media_loma",
                "Media Loma de Transición",
                "#3b82f6",
                "Posición intermedia de tránsito hídrico; excelente provisión de agua útil en años secos y drenaje aceptable en años normales.",
            ),
            (
                "bajo_dulce",
                "Bajo Tendido / Bajo Dulce",
                "#f59e0b",
                "Acumulación temporal de escorrentía y napa cercana. Apto para cultivos tolerantes (Sorgo, Soja grupo largo) o pasturas consociadas.",
            ),
            (
                "bajo_inundable",
                "Bajo Inundable / Cubeta",
                "#ef4444",
                "Depresión receptora con anegamiento frecuente o alcalinidad sódica (horizonte Bt nátrico). Uso exclusivo ganadero (Agropiro, Lotus tenuis) o reserva hídrica.",
            ),
        ]

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

    # Construcción de los Perfiles de Elevación (Cortes Topográficos)
    def _build_profile_from_indices(
        profile_id: str,
        title: str,
        coords_rc: List[Tuple[int, int]],
    ) -> ElevationProfile:
        pts: List[ProfilePoint] = []
        cum_dist = 0.0
        prev_lat, prev_lon, prev_z = None, None, None
        max_local_s = 0.0

        for idx, (r, c) in enumerate(coords_rc):
            plat = lats[r]
            plon = lons[c]
            pz = z_grid[r][c]
            pzone = zone_Grid[r][c]
            # Napa freática suavizada (sigue el 35% de la variación superficial sobre la base freática)
            wt_msnm = round(water_table_base_msnm + (pz - z_mean) * 0.35, 2)
            # En bajos inundables de la Pampa Deprimida la napa puede aflorar
            wt_depth = round(max(0.0, pz - wt_msnm), 2)

            if prev_lat is not None and prev_lon is not None and prev_z is not None:
                d_m = math.hypot(
                    (plat - prev_lat) * 111000.0,
                    (plon - prev_lon) * 111000.0 * math.cos(math.radians(lat)),
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
    # 1. Corte Norte -> Sur (de fila superior a fila inferior por columna central)
    ns_rc = [(grid_n - 1 - i, mid) for i in range(grid_n)]
    # 2. Corte Oeste -> Este (por fila central de izquierda a derecha)
    we_rc = [(mid, i) for i in range(grid_n)]
    # 3. Diagonal / Eje de Drenaje (NO -> SE)
    diag_rc = [(grid_n - 1 - i, i) for i in range(grid_n)]

    profiles = [
        _build_profile_from_indices("north_south", "Transecta Norte → Sur (N-S)", ns_rc),
        _build_profile_from_indices("west_east", "Transecta Oeste → Este (O-E)", we_rc),
        _build_profile_from_indices(
            "drainage_axis", "Transecta Diagonal NO → SE (Eje de Escurrimiento)", diag_rc
        ),
    ]

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
        estimated_water_table_depth_m=round(max(0.25, base_wt + (center_z - z_mean) * 0.4), 2),
    )

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
    )
