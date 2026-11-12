import ast
import asyncio
import logging
import math
import re
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from ..config import PLANETARY_DATA_URL, PLANETARY_STAC_URL
from ..schemas import TileLayerInfo

logger = logging.getLogger(__name__)

WORLDCOVER_LABELS = {
    10: "Bosque / Arbolado",
    20: "Arbustal / Matorral",
    30: "Pastizal Natural",
    40: "Cultivo Agrícola",
    50: "Área Urbana / Edificada",
    60: "Suelo Desnudo / Roca / Arena",
    70: "Nieve / Hielo",
    80: "Cuerpo de Agua Permanente",
    90: "Humedal / Bañado",
    95: "Manglares",
    100: "Musgo / Líquenes",
}


def get_bbox(lat: float, lon: float, buffer_km: float = 1.0) -> List[float]:
    """Calcula bounding box [min_lon, min_lat, max_lon, max_lat] para un radio dado en km."""
    deg_lat = buffer_km / 111.0
    deg_lon = buffer_km / (111.0 * max(0.1, math.cos(math.radians(lat))))
    return [
        round(lon - deg_lon, 5),
        round(lat - deg_lat, 5),
        round(lon + deg_lon, 5),
        round(lat + deg_lat, 5),
    ]


def _haversine_local_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia métrica rápida en superficie terrestre local."""
    mean_lat_rad = math.radians((lat1 + lat2) * 0.5)
    dy = (lat2 - lat1) * 111132.0
    dx = (lon2 - lon1) * 111320.0 * max(0.1, math.cos(mean_lat_rad))
    return math.hypot(dx, dy)


def _parse_npy_grid(raw: bytes) -> Tuple[List[List[float]], Optional[List[List[int]]]]:
    """
    Decodifica un archivo NumPy (.npy v1/v2) retornado por Planetary Computer TiTiler.
    Reorienta las filas verticalmente para devolver el orden Sur -> Norte (fila 0 = min_lat).
    """
    if len(raw) < 12 or raw[:6] != b"\x93NUMPY":
        raise ValueError("Payload NPY inválido")

    ver_major = raw[6]
    if ver_major == 1:
        hlen = struct.unpack("<H", raw[8:10])[0]
        hdr_start = 10
    else:
        hlen = struct.unpack("<I", raw[8:12])[0]
        hdr_start = 12

    offset = hdr_start + hlen
    header_str = raw[hdr_start:offset].decode("latin1").strip()
    header_meta = ast.literal_eval(header_str)
    shape = tuple(int(x) for x in header_meta["shape"])
    descr = str(header_meta["descr"])

    if "f4" in descr:
        fmt_char, esize = "f", 4
    elif "f8" in descr:
        fmt_char, esize = "d", 8
    elif "i2" in descr:
        fmt_char, esize = "h", 2
    elif "u2" in descr:
        fmt_char, esize = "H", 2
    else:
        fmt_char, esize = "B", 1

    endian = ">" if descr.startswith(">") else "<"
    bands = shape[0] if len(shape) == 3 else 1
    rows, cols = (shape[1], shape[2]) if len(shape) == 3 else (shape[0], shape[1])
    total = bands * rows * cols
    vals = struct.unpack(f"{endian}{total}{fmt_char}", raw[offset : offset + total * esize])

    plane_size = rows * cols
    band0 = [[float(vals[r * cols + c]) for c in range(cols)] for r in range(rows)]
    band1 = (
        [[int(vals[plane_size + r * cols + c]) for c in range(cols)] for r in range(rows)]
        if bands > 1
        else None
    )

    # TiTiler devuelve fila 0 en el borde Norte; invertimos para alinear Sur -> Norte
    band0_sn = list(reversed(band0))
    band1_sn = list(reversed(band1)) if band1 is not None else None
    return band0_sn, band1_sn


async def _search_stac_items(
    client: httpx.AsyncClient,
    collection: str,
    bbox: List[float],
    limit: int = 4,
    extra_body: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Consulta STAC search para una colección y bounding box."""
    body: Dict[str, Any] = {
        "collections": [collection],
        "bbox": bbox,
        "limit": limit,
    }
    if extra_body:
        body.update(extra_body)
    try:
        res = await client.post(f"{PLANETARY_STAC_URL}/search", json=body)
        if res.status_code == 200:
            return res.json().get("features", [])
    except Exception as exc:
        logger.debug(f"STAC search warning ({collection}): {exc}")
    return []


def _select_latest_worldcover_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Conserva únicamente los tiles del año más reciente de ESA WorldCover evitando mezclar 2020/2021."""
    if not features:
        return []
    has_2021 = any("2021" in f.get("id", "") for f in features)
    filtered = [f for f in features if ("2021" in f.get("id", "")) == has_2021] if has_2021 else features
    seen_ids = set()
    unique: List[Dict[str, Any]] = []
    for f in filtered:
        fid = f.get("id", "")
        if fid and fid not in seen_ids:
            seen_ids.add(fid)
            unique.append(f)
    return unique[:4]


async def _fetch_merged_grid(
    client: httpx.AsyncClient,
    collection: str,
    features: List[Dict[str, Any]],
    asset: str,
    bbox: List[float],
    size_n: int,
    valid_fn: Callable[[float, int], bool],
) -> Tuple[List[List[Optional[float]]], List[List[bool]]]:
    """
    Descarga en paralelo los `.npy` de todos los tiles que cruzan `bbox` y los fusiona
    celda a celda preservando los valores válidos en fronteras de cuadrángulos.
    """
    grid: List[List[Optional[float]]] = [[None] * size_n for _ in range(size_n)]
    mask_ok: List[List[bool]] = [[False] * size_n for _ in range(size_n)]

    if not features:
        return grid, mask_ok

    urls = [
        (
            f"{PLANETARY_DATA_URL}/item/bbox/{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"
            f"/{size_n}x{size_n}.npy?collection={collection}&item={f['id']}&assets={asset}"
        )
        for f in features[:4]
    ]

    responses = await asyncio.gather(
        *[client.get(u) for u in urls],
        return_exceptions=True,
    )

    for resp in responses:
        if isinstance(resp, Exception) or resp.status_code != 200:
            continue
        try:
            vals, bmask = _parse_npy_grid(resp.content)
        except Exception:
            continue

        for r in range(min(size_n, len(vals))):
            for c in range(min(size_n, len(vals[r]))):
                if mask_ok[r][c]:
                    continue
                v = vals[r][c]
                m = bmask[r][c] if bmask is not None else 255
                if valid_fn(v, m):
                    grid[r][c] = v
                    mask_ok[r][c] = True

    return grid, mask_ok


async def _fetch_worldcover_histogram(
    client: httpx.AsyncClient,
    wc_features: List[Dict[str, Any]],
    bbox: List[float],
) -> Dict[str, Any]:
    """Obtiene el conteo real de píxeles a 10m por categoría de ESA WorldCover en la parcela."""
    if not wc_features:
        return {"breakdown": {}, "raw_counts": {}, "total_pixels": 0, "masked_pixels": 0}

    poly = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[
                [bbox[0], bbox[1]],
                [bbox[2], bbox[1]],
                [bbox[2], bbox[3]],
                [bbox[0], bbox[3]],
                [bbox[0], bbox[1]],
            ]],
        },
        "properties": {},
    }

    urls = [
        f"{PLANETARY_DATA_URL}/item/statistics?collection=esa-worldcover&item={f['id']}&assets=map&categorical=true"
        for f in wc_features[:4]
    ]
    resps = await asyncio.gather(
        *[client.post(u, json=poly) for u in urls],
        return_exceptions=True,
    )

    raw_counts: Dict[int, int] = {}
    masked_total = 0
    for resp in resps:
        if isinstance(resp, Exception) or resp.status_code != 200:
            continue
        try:
            stats = resp.json().get("properties", {}).get("statistics", {})
            band = stats.get("map_b1") or next(iter(stats.values()), {})
            hist = band.get("histogram", [[], []])
            counts, values = hist[0], hist[1]
            for cnt, val in zip(counts, values):
                code = int(round(float(val)))
                if code > 0:
                    raw_counts[code] = raw_counts.get(code, 0) + int(cnt)
            masked_total += int(band.get("masked_pixels", 0))
        except Exception:
            continue

    total_valid = sum(raw_counts.values())
    if total_valid <= 0:
        return {"breakdown": {}, "raw_counts": {}, "total_pixels": 0, "masked_pixels": masked_total}

    breakdown: Dict[str, float] = {}
    for code, cnt in sorted(raw_counts.items(), key=lambda kv: kv[1], reverse=True):
        label = WORLDCOVER_LABELS.get(code, f"Clase {code}")
        breakdown[label] = round((cnt / total_valid) * 100.0, 1)

    return {
        "breakdown": breakdown,
        "raw_counts": raw_counts,
        "total_pixels": total_valid,
        "masked_pixels": masked_total,
    }


async def _fetch_point_values(
    client: httpx.AsyncClient,
    collection: str,
    features: List[Dict[str, Any]],
    assets: List[str],
    lon: float,
    lat: float,
) -> Optional[List[float]]:
    """Consulta el valor puntual exacto del píxel sobre un ítem de Planetary Computer."""
    if not features:
        return None
    asset_qs = "&".join(f"assets={a}" for a in assets)
    for f in features[:3]:
        url = f"{PLANETARY_DATA_URL}/item/point/{lon},{lat}?collection={collection}&item={f['id']}&{asset_qs}"
        try:
            res = await client.get(url)
            if res.status_code == 200:
                vals = res.json().get("values")
                if vals and len(vals) == len(assets):
                    return [float(v) for v in vals]
        except Exception:
            continue
    return None


async def _fetch_sentinel2_metrics(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    bbox: List[float],
) -> Dict[str, Any]:
    """Consulta la escena Sentinel-2 L2A más reciente con baja nubosidad y calcula NDVI/NDWI/MNDWI reales."""
    feats = await _search_stac_items(
        client,
        "sentinel-2-l2a",
        bbox,
        limit=3,
        extra_body={
            "sortby": [{"field": "properties.datetime", "direction": "desc"}],
            "query": {"eo:cloud_cover": {"lt": 30}},
        },
    )
    if not feats:
        feats = await _search_stac_items(
            client,
            "sentinel-2-l2a",
            bbox,
            limit=2,
            extra_body={
                "sortby": [{"field": "properties.datetime", "direction": "desc"}],
                "query": {"eo:cloud_cover": {"lt": 75}},
            },
        )
    if not feats:
        return {"item_id": None, "date": None, "ndvi": 0.0, "ndwi": -0.25, "mndwi": -0.35}

    feat = feats[0]
    fid = feat["id"]
    scene_date = (feat.get("properties", {}).get("datetime") or "")[:10] or None
    baseline_str = str(feat.get("properties", {}).get("s2:processing_baseline", "04.00"))
    try:
        baseline_num = float(baseline_str)
    except ValueError:
        baseline_num = 4.0

    vals = await _fetch_point_values(
        client, "sentinel-2-l2a", [feat], ["B03", "B04", "B08", "B11"], lon, lat
    )
    if not vals or all(v <= 0 or math.isnan(v) for v in vals):
        return {"item_id": fid, "date": scene_date, "ndvi": 0.0, "ndwi": -0.25, "mndwi": -0.35}

    offset = 1000.0 if baseline_num >= 4.0 and min(vals) > 900.0 else 0.0
    b3, b4, b8, b11 = [max(1.0, v - offset) for v in vals]
    ndvi = round(max(-1.0, min(1.0, (b8 - b4) / (b8 + b4))), 3)
    ndwi = round(max(-1.0, min(1.0, (b3 - b8) / (b3 + b8))), 3)
    mndwi = round(max(-1.0, min(1.0, (b3 - b11) / (b3 + b11))), 3)
    return {"item_id": fid, "date": scene_date, "ndvi": ndvi, "ndwi": ndwi, "mndwi": mndwi}


async def _fetch_sentinel1_metrics(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
    bbox: List[float],
) -> Dict[str, Any]:
    """Consulta retrodispersión radar SAR real de Sentinel-1 RTC (polarización VV en dB)."""
    feats = await _search_stac_items(
        client,
        "sentinel-1-rtc",
        bbox,
        limit=2,
        extra_body={"sortby": [{"field": "properties.datetime", "direction": "desc"}]},
    )
    if not feats:
        return {"item_id": None, "sar_db": -12.0}

    feat = feats[0]
    vals = await _fetch_point_values(client, "sentinel-1-rtc", [feat], ["vv"], lon, lat)
    if not vals or vals[0] <= 0 or math.isnan(vals[0]):
        return {"item_id": feat["id"], "sar_db": -12.0}

    sar_db = round(max(-32.0, min(5.0, 10.0 * math.log10(max(1e-6, vals[0])))), 1)
    return {"item_id": feat["id"], "sar_db": sar_db}


async def _reverse_geocode_nominatim(
    client: httpx.AsyncClient,
    lat: float,
    lon: float,
) -> Dict[str, Any]:
    """Obtiene ubicación real administrativa/toponímica desde OpenStreetMap Nominatim."""
    url = f"https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat={lat}&lon={lon}&zoom=14&addressdetails=1"
    try:
        res = await client.get(url, headers={"User-Agent": "AgroJEV-PBA/2.0 (geospatial-audit)"}, timeout=2.2)
        if res.status_code != 200:
            return {}
        data = res.json()
        if "error" in data:
            return {"error": data["error"]}
        addr = data.get("address", {}) or {}
        parts: List[str] = []
        for k in ("suburb", "village", "town", "city", "municipality", "county", "state_district", "state", "country"):
            v = addr.get(k)
            if v and v not in parts:
                parts.append(v)
        label = ", ".join(parts[:3]) if parts else (data.get("display_name") or "").split(",")[0]
        return {
            "label": label or f"{lat:.4f}, {lon:.4f}",
            "category": data.get("category", ""),
            "type": data.get("type", ""),
            "name": data.get("name", ""),
            "country": addr.get("country", ""),
            "state": addr.get("state", ""),
            "county": addr.get("county") or addr.get("state_district") or "",
        }
    except Exception:
        return {}


def _extract_water_components(water_bool: List[List[bool]]) -> List[Dict[str, Any]]:
    """Extrae componentes conexas de agua mediante BFS (8-vecindad) con métricas de forma y contacto a bordes."""
    rows = len(water_bool)
    cols = len(water_bool[0]) if rows else 0
    visited = [[False] * cols for _ in range(rows)]
    comps: List[Dict[str, Any]] = []
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]

    for r0 in range(rows):
        for c0 in range(cols):
            if not water_bool[r0][c0] or visited[r0][c0]:
                continue
            queue = [(r0, c0)]
            visited[r0][c0] = True
            cells = []
            touches = set()
            min_r, max_r, min_c, max_c = r0, r0, c0, c0
            while queue:
                r, c = queue.pop()
                cells.append((r, c))
                if r == 0:
                    touches.add("S")
                if r == rows - 1:
                    touches.add("N")
                if c == 0:
                    touches.add("W")
                if c == cols - 1:
                    touches.add("E")
                min_r, max_r = min(min_r, r), max(max_r, r)
                min_c, max_c = min(min_c, c), max(max_c, c)
                for dr, dc in offsets:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols and not visited[nr][nc] and water_bool[nr][nc]:
                        visited[nr][nc] = True
                        queue.append((nr, nc))

            span_r = max_r - min_r + 1
            span_c = max_c - min_c + 1
            bbox_fill = len(cells) / max(1, span_r * span_c)
            aspect = max(span_r, span_c) / max(1, min(span_r, span_c))
            comps.append({
                "cells": cells,
                "size": len(cells),
                "touches": touches,
                "aspect": aspect,
                "bbox_fill": bbox_fill,
            })

    comps.sort(key=lambda x: x["size"], reverse=True)
    return comps


def _grid_coords(bbox: List[float], size_n: int) -> Tuple[List[float], List[float]]:
    """Retorna lats (Sur->Norte) y lons (Oeste->Este) correspondientes a una grilla size_n x size_n."""
    min_lon, min_lat, max_lon, max_lat = bbox
    lats = [min_lat + (max_lat - min_lat) * (r + 0.5) / size_n for r in range(size_n)]
    lons = [min_lon + (max_lon - min_lon) * (c + 0.5) / size_n for c in range(size_n)]
    return lats, lons


def _fill_dem_grid_17x17(
    dem_vals: List[List[Optional[float]]],
    dem_mask: List[List[bool]],
    water_mask_17: List[List[int]],
    has_dem_items: bool,
) -> Tuple[List[List[float]], int]:
    """
    Construye la grilla float 17x17 sin huecos a partir de Copernicus DEM real:
    - Si una celda es agua marina / sin tile terrestre (nodata en DEM junto a cota <= 5m), asigna 0.0 m.
    - Si una celda terrestre puntual tiene nodata, interpola desde sus vecinos válidos.
    """
    n = len(dem_vals)
    valid_vals = [
        dem_vals[r][c]
        for r in range(n)
        for c in range(n)
        if dem_mask[r][c] and dem_vals[r][c] is not None
    ]

    if not has_dem_items or not valid_vals:
        return [[0.0] * n for _ in range(n)], 0

    min_valid = min(valid_vals)
    out: List[List[Optional[float]]] = [
        [dem_vals[r][c] if dem_mask[r][c] else None for c in range(n)]
        for r in range(n)
    ]

    # Marcar nodata sobre cuerpos de agua al nivel del mar como 0.0 m
    if min_valid <= 6.0:
        for r in range(n):
            for c in range(n):
                if out[r][c] is None and water_mask_17[r][c] == 2:
                    out[r][c] = 0.0

    # Iterativamente rellenar cualquier celda interior faltante con media de vecinos válidos
    offsets = [(-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)]
    for _ in range(6):
        missing = False
        next_out = [row[:] for row in out]
        for r in range(n):
            for c in range(n):
                if out[r][c] is not None:
                    continue
                missing = True
                nbs = []
                for dr, dc in offsets:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < n and 0 <= nc < n and out[nr][nc] is not None:
                        nbs.append(out[nr][nc])
                if nbs:
                    next_out[r][c] = sum(nbs) / len(nbs)
        out = next_out
        if not missing:
            break

    fallback_z = max(0.0, min_valid) if min_valid > 6.0 else 0.0
    final_grid = [
        [round(float(out[r][c] if out[r][c] is not None else fallback_z), 2) for c in range(n)]
        for r in range(n)
    ]
    return final_grid, len(valid_vals)


def _analyze_hydro_and_environment(
    lat: float,
    lon: float,
    parcel_bbox: List[float],
    ctx_bbox: List[float],
    parcel_wc: List[List[Optional[float]]],
    parcel_wc_mask: List[List[bool]],
    parcel_jrc: List[List[Optional[float]]],
    parcel_dem_17: List[List[float]],
    ctx_wc: List[List[Optional[float]]],
    ctx_wc_mask: List[List[bool]],
    ctx_dem: List[List[Optional[float]]],
    ctx_dem_mask: List[List[bool]],
    wc_hist: Dict[str, Any],
    center_wc: Optional[int],
    center_jrc: float,
    jrc_seasonality_months: int,
    has_dem_items: bool,
    has_wc_items: bool,
    nominatim: Dict[str, Any],
    ndvi: float,
    mndwi: float,
) -> Dict[str, Any]:
    """
    Analiza geomorfología hídrica, presencia de costas marinas/estuarios, ríos/arroyos,
    lagunas, humedales, áreas urbanas y coberturas terrestres reales sin hardcodeo geográfico.
    """
    n_p = len(parcel_wc)
    n_c = len(ctx_wc)
    n_cd = len(ctx_dem)

    # Identificar celdas oceánicas sin cobertura terrestre en mosaicos WorldCover/DEM
    ctx_valid_dems = [
        ctx_dem[r][c]
        for r in range(n_cd)
        for c in range(len(ctx_dem[r]))
        if ctx_dem_mask[r][c] and ctx_dem[r][c] is not None
    ]
    ctx_min_dem = min(ctx_valid_dems) if ctx_valid_dems else 0.0
    ctx_max_dem = max(ctx_valid_dems) if ctx_valid_dems else 0.0

    # Un nodata en WorldCover solo representa mar abierto cuando hay cota mínima de nivel del mar (<= 2.5m) o faltan tiles
    sea_nodata_possible = (not has_wc_items) or (ctx_min_dem <= 2.5)

    p_water = [[False] * n_p for _ in range(n_p)]
    p_wetland = [[False] * n_p for _ in range(n_p)]
    for r in range(n_p):
        for c in range(n_p):
            wc_v = int(parcel_wc[r][c]) if (parcel_wc_mask[r][c] and parcel_wc[r][c] is not None) else None
            jrc_v = parcel_jrc[r][c] if parcel_jrc[r][c] is not None else 0.0
            is_sea_gap = (wc_v is None and sea_nodata_possible)
            if wc_v == 80 or is_sea_gap or jrc_v >= 45.0:
                p_water[r][c] = True
            elif wc_v in (90, 95) or jrc_v >= 15.0:
                p_wetland[r][c] = True

    c_water = [[False] * n_c for _ in range(n_c)]
    c_land = [[False] * n_c for _ in range(n_c)]
    c_sea_level_water = 0
    for r in range(n_c):
        dr = min(n_cd - 1, int(round(r * (n_cd - 1) / max(1, n_c - 1)))) if n_cd > 0 else 0
        for c in range(n_c):
            dc = min(len(ctx_dem[dr]) - 1, int(round(c * (len(ctx_dem[dr]) - 1) / max(1, n_c - 1)))) if n_cd > 0 else 0
            wc_v = int(ctx_wc[r][c]) if (ctx_wc_mask[r][c] and ctx_wc[r][c] is not None) else None
            is_sea_gap = (wc_v is None and sea_nodata_possible)
            d_v = ctx_dem[dr][dc] if (n_cd > 0 and ctx_dem_mask[dr][dc] and ctx_dem[dr][dc] is not None) else 0.0
            if wc_v == 80 or is_sea_gap:
                c_water[r][c] = True
                if d_v <= 1.2:
                    c_sea_level_water += 1
            elif wc_v is not None:
                c_land[r][c] = True

    total_p = max(1, n_p * n_p)
    total_c = max(1, n_c * n_c)
    p_water_ratio = sum(1 for r in range(n_p) for c in range(n_p) if p_water[r][c]) / total_p
    c_water_ratio = sum(1 for r in range(n_c) for c in range(n_c) if c_water[r][c]) / total_c
    c_land_ratio = sum(1 for r in range(n_c) for c in range(n_c) if c_land[r][c]) / total_c

    # Porcentajes exactos a 10m del histograma de WorldCover (o respaldo desde grilla)
    raw_counts: Dict[int, int] = wc_hist.get("raw_counts", {})
    total_px = wc_hist.get("total_pixels", 0)

    def _wc_pct(code: int) -> float:
        if total_px > 0:
            return round((raw_counts.get(code, 0) / total_px) * 100.0, 1)
        cnt = sum(
            1
            for r in range(n_p)
            for c in range(n_p)
            if parcel_wc_mask[r][c] and int(parcel_wc[r][c] or -1) == code
        )
        return round((cnt / total_p) * 100.0, 1)

    wc_water_pct = _wc_pct(80)
    # Si la grilla detecta huecos marinos no contados en el histograma, incorporar esa fracción
    effective_water_pct = max(wc_water_pct, round(p_water_ratio * 100.0, 1))
    wetland_pct = round(_wc_pct(90) + _wc_pct(95), 1)
    cropland_pct = _wc_pct(40)
    grassland_pct = _wc_pct(30)
    shrub_pct = _wc_pct(20)
    tree_pct = _wc_pct(10)
    urban_pct = _wc_pct(50)
    bare_pct = _wc_pct(60)
    snow_pct = _wc_pct(70)

    # Cálculo de distancia mínima real en metros desde el centro hasta el agua
    p_lats, p_lons = _grid_coords(parcel_bbox, n_p)
    c_lats, c_lons = _grid_coords(ctx_bbox, n_c)
    center_r, center_c = n_p // 2, n_p // 2
    center_is_water = (
        p_water[center_r][center_c]
        or center_wc == 80
        or center_jrc >= 55.0
        or mndwi >= 0.25
        or (center_wc is None and sea_nodata_possible)
    )

    min_water_dist_m: Optional[float] = 0.0 if center_is_water else None
    if not center_is_water:
        dists = [
            _haversine_local_m(lat, lon, p_lats[r], p_lons[c])
            for r in range(n_p)
            for c in range(n_p)
            if p_water[r][c]
        ]
        if dists:
            min_water_dist_m = round(min(dists), 0)
        else:
            # Buscar en el contexto (~4 km)
            ctx_dists = [
                _haversine_local_m(lat, lon, c_lats[r], c_lons[c])
                for r in range(n_c)
                for c in range(n_c)
                if c_water[r][c]
            ]
            if ctx_dists:
                min_water_dist_m = round(min(ctx_dists), 0)
            elif wc_water_pct >= 0.15:
                # Arroyo angosto detectado en el histograma de 10m pero entre nodos de grilla
                min_water_dist_m = round(
                    _haversine_local_m(lat, lon, parcel_bbox[1], parcel_bbox[0]) * 0.45, 0
                )

    # Detección de Océano / Costa / Estuario / Río / Laguna por topología BFS + cotas reales
    c_comps = _extract_water_components(c_water)
    p_comps = _extract_water_components(p_water)
    largest_c = c_comps[0] if c_comps else None

    parcel_flat_dem = [v for row in parcel_dem_17 for v in row]
    parcel_min_dem = min(parcel_flat_dem) if parcel_flat_dem else 0.0
    parcel_max_dem = max(parcel_flat_dem) if parcel_flat_dem else 0.0
    center_dem = parcel_dem_17[len(parcel_dem_17) // 2][len(parcel_dem_17[0]) // 2]

    nom_type = (nominatim.get("type") or "").lower()
    nom_cat = (nominatim.get("category") or "").lower()
    has_land_address = bool(nominatim.get("county") or nominatim.get("state"))
    has_any_geo = bool(has_land_address or nominatim.get("country"))

    # 1. Océano / Mar Abierto
    is_open_ocean = (
        (not has_dem_items and not has_wc_items)
        or (effective_water_pct >= 98.0 and c_water_ratio >= 0.98 and ctx_max_dem <= 1.2 and not has_any_geo)
    )

    # 2. Borde Costero / Mar Litoral / Estuario
    large_sea_water = (
        largest_c is not None
        and (largest_c["size"] / total_c) >= 0.14
        and len(largest_c["touches"]) >= 1
        and (c_sea_level_water / total_c) >= 0.12
        and ctx_min_dem <= 1.0
    )
    coast_detected = (not is_open_ocean) and (
        (large_sea_water and c_land_ratio >= 0.06)
        or (nom_type in ("sea", "ocean", "bay", "strait", "beach", "coastline"))
    )

    # 3. Curso Fluvial (Río / Arroyo / Canal) vs Laguna Interior
    river_detected = False
    lake_detected = False

    if not is_open_ocean:
        for comp in p_comps:
            touches_cnt = len(comp["touches"])
            comp_ratio = comp["size"] / total_p
            # Un río que atraviesa el lote suele tocar >=2 bordes o ser elongado ocupando < 55% del lote
            is_linear_or_passing = (
                (touches_cnt >= 2 and comp_ratio < 0.72)
                or (comp["aspect"] >= 2.2 and comp_ratio >= 0.01)
                or (comp["bbox_fill"] < 0.42 and comp["size"] >= 4)
            )
            # En zonas continentales sobre > 2m o con tierra a ambos lados de un cauce
            if is_linear_or_passing and (not coast_detected or parcel_max_dem > 2.5):
                river_detected = True
                break

        # También chequeamos en contexto si un río pasa cerca (< 1.6 km) aunque el lote sea solo ribereño
        if not river_detected and min_water_dist_m is not None and min_water_dist_m <= 1600:
            for comp in c_comps:
                comp_ratio = comp["size"] / total_c
                if (
                    len(comp["touches"]) >= 2
                    and comp_ratio < 0.35
                    and (not coast_detected or parcel_min_dem > 1.5)
                ) or (wetland_pct >= 25.0 and wc_water_pct >= 2.5):
                    river_detected = True
                    break

        # Arroyo angosto detectado en píxeles de 10m (0.15%..18% del lote) sobre terreno inclinado/continental
        if not river_detected and not coast_detected and 0.15 <= wc_water_pct <= 18.0 and (parcel_min_dem > 1.5 or wetland_pct >= 15.0):
            river_detected = True

        if nom_type in ("river", "stream", "canal", "riverbank", "waterway") or nom_cat == "waterway":
            river_detected = True

        # Si hay cuerpo de agua grande cerrado y no es río ni costa marina ni océano -> laguna / embalse
        if not river_detected and not coast_detected and (effective_water_pct >= 18.0 or (center_is_water and wc_water_pct >= 5.0)):
            lake_detected = True

    # Estimar pendiente promedio rápida del lote para decidir si es relieve montañoso/serrano
    cell_step_m = _haversine_local_m(
        parcel_bbox[1], parcel_bbox[0], parcel_bbox[3], parcel_bbox[0]
    ) / max(1, len(parcel_dem_17) - 1)
    d_n = len(parcel_dem_17)
    slope_samples = []
    for r in range(1, d_n - 1):
        for c in range(1, d_n - 1):
            gx = (parcel_dem_17[r][c + 1] - parcel_dem_17[r][c - 1]) / (2.0 * max(1.0, cell_step_m))
            gy = (parcel_dem_17[r + 1][c] - parcel_dem_17[r - 1][c]) / (2.0 * max(1.0, cell_step_m))
            slope_samples.append(math.hypot(gx, gy) * 100.0)
    mean_slope_pct_est = (sum(slope_samples) / len(slope_samples)) if slope_samples else 0.0
    relief_amp_est = parcel_max_dem - parcel_min_dem

    is_urban = (not center_is_water) and (center_wc == 50 or urban_pct >= 38.0)
    is_mountain_steep = (not is_open_ocean and not center_is_water) and (
        mean_slope_pct_est >= 7.5
        or (relief_amp_est >= 85.0 and mean_slope_pct_est >= 4.5)
        or (center_dem >= 310.0 and mean_slope_pct_est >= 4.8 and cropland_pct < 15.0)
    )
    is_wetland = (not is_open_ocean) and (
        center_wc in (90, 95)
        or wetland_pct >= 28.0
        or (wetland_pct + effective_water_pct >= 45.0 and cropland_pct < 20.0)
    )

    # Clasificación unificada del entorno detectado y cuerpo de agua
    if is_open_ocean:
        water_body_type = "oceano"
        env_type = "oceano_mar_abierto"
        env_label = "Océano / Mar Abierto (Sin Suelo Terrestre)"
    elif center_is_water:
        if coast_detected or (effective_water_pct >= 95.0 and ctx_max_dem <= 2.0 and has_any_geo):
            lake_detected = False
            water_body_type = "mar_costero_estuario"
            env_type = "cuerpo_agua_abierto"
            env_label = "Estuario / Río Ancho o Agua Costera Litoral"
        elif river_detected:
            water_body_type = "rio_arroyo"
            env_type = "cauce_fluvial_rio"
            env_label = "Cauce Fluvial Activo (Río o Arroyo Permanente)"
        else:
            water_body_type = "laguna_embalse"
            env_type = "laguna_cuerpo_agua"
            env_label = "Laguna o Espejo de Agua Continental"
    elif is_urban:
        water_body_type = (
            "mar_costero_estuario" if coast_detected else (
                "rio_arroyo" if river_detected else ("laguna_embalse" if lake_detected else "ninguno")
            )
        )
        env_type = "area_urbana"
        env_label = f"Área Urbana / Periurbana Consolidada ({urban_pct:.0f}% edificado)"
    elif coast_detected and (min_water_dist_m is not None and min_water_dist_m <= 800 or effective_water_pct >= 8.0 or bare_pct >= 12.0):
        water_body_type = "mar_costero_estuario"
        env_type = "borde_costero_marino"
        env_label = (
            "Acantilado / Costa Marina" if mean_slope_pct_est >= 3.5 or relief_amp_est >= 18.0
            else "Zona Costera / Playa / Litoral Marino"
        )
    elif is_wetland:
        water_body_type = "humedal_banado" if not river_detected else "rio_arroyo"
        env_type = "humedal_delta"
        env_label = (
            "Humedal Fluvial / Delta con Cursos de Agua" if river_detected
            else ("Marisma / Humedal Costero" if coast_detected else "Humedal Herbáceo / Bañado")
        )
    elif river_detected and (wc_water_pct >= 0.15 or (min_water_dist_m is not None and min_water_dist_m <= 1100)):
        water_body_type = "rio_arroyo"
        env_type = "lote_ribereño_fluvial"
        env_label = f"Parcela Ribereña / Próxima a Curso Fluvial ({int(min_water_dist_m or 0)} m)"
    elif is_mountain_steep:
        water_body_type = "rio_arroyo" if river_detected else "ninguno"
        env_type = "relieve_serrano_escarpado"
        env_label = f"Macizo Serrano / Relieve Montañoso Escarpado (Pend. {mean_slope_pct_est:.1f}%)"
    elif bare_pct >= 45.0 or snow_pct >= 30.0:
        water_body_type = "mar_costero_estuario" if coast_detected else "ninguno"
        env_type = "suelo_desnudo_arenal_roca"
        env_label = "Nieve / Glaciar de Alta Montaña" if snow_pct >= 30.0 else "Arenal / Médanos / Suelo Desnudo o Rocoso"
    elif tree_pct >= 55.0 and cropland_pct < 20.0:
        water_body_type = "rio_arroyo" if river_detected else "ninguno"
        env_type = "bosque_monte"
        env_label = "Bosque / Monte Nativo o Forestación Densa"
    else:
        water_body_type = (
            "mar_costero_estuario" if coast_detected else (
                "rio_arroyo" if river_detected else ("laguna_embalse" if lake_detected else "ninguno")
            )
        )
        env_type = "rural_agricola"
        if coast_detected:
            env_label = f"Terreno Rural en Franja Costera ({int(min_water_dist_m or 0)} m del borde litoral)"
        elif lake_detected:
            env_label = f"Terreno Rural Próximo a Laguna ({int(min_water_dist_m or 0)} m)"
        else:
            env_label = "Terreno Rural / Uso Agropecuario o Pastoril"

    # Reescalar grilla de máscara de agua a 17x17 para overlay preciso en el visor Leaflet
    mask_17: List[List[int]] = []
    for r17 in range(17):
        row_m: List[int] = []
        sr = min(n_p - 1, int(round(r17 * (n_p - 1) / 16.0)))
        for c17 in range(17):
            sc = min(n_p - 1, int(round(c17 * (n_p - 1) / 16.0)))
            if p_water[sr][sc]:
                row_m.append(2)
            elif p_wetland[sr][sc]:
                row_m.append(1)
            else:
                row_m.append(0)
        mask_17.append(row_m)

    # Construir descripción hidrográfica detallada
    if is_open_ocean:
        hydro_desc = "Masa oceánica abierta (100% agua profunda a nivel del mar)."
    elif water_body_type == "mar_costero_estuario":
        dist_txt = "sobre línea de agua costera" if center_is_water else f"a ~{int(min_water_dist_m or 0)} m del borde litoral"
        hydro_desc = f"Costa marítima / estuario detectado ({dist_txt}; {c_water_ratio*100:.0f}% del entorno de 4 km es agua a cota ≤1m)."
    elif water_body_type == "rio_arroyo":
        dist_txt = "punto ubicado dentro del cauce" if center_is_water else f"cauce a ~{int(min_water_dist_m or 0)} m del centro"
        hydro_desc = f"Curso fluvial (río/arroyo) detectado ({dist_txt}; {wc_water_pct:.1f}% espejo de agua en parcela)."
    elif water_body_type == "laguna_embalse":
        dist_txt = "sobre espejo lacustre" if center_is_water else f"laguna a ~{int(min_water_dist_m or 0)} m"
        hydro_desc = f"Cuerpo de agua continental cerrado / laguna ({dist_txt}; estacionalidad JRC {jrc_seasonality_months}/12 meses)."
    elif is_wetland:
        hydro_desc = f"Planicie de humedal / bañado ({wetland_pct:.1f}% cobertura hidrófila ESA WorldCover 10m)."
    else:
        hydro_desc = "Sin cursos fluviales ni cuerpos de agua superficiales significativos dentro del radio inmediato."

    return {
        "environment_type": env_type,
        "environment_label": env_label,
        "water_body_type": water_body_type,
        "water_distance_m": min_water_dist_m,
        "coast_detected": coast_detected or is_open_ocean,
        "river_detected": river_detected,
        "urban_detected": is_urban,
        "center_is_water": center_is_water,
        "is_open_ocean": is_open_ocean,
        "is_wetland": is_wetland,
        "is_mountain_steep": is_mountain_steep,
        "effective_water_pct": round(effective_water_pct, 1),
        "wc_water_pct": wc_water_pct,
        "wetland_pct": wetland_pct,
        "cropland_pct": cropland_pct,
        "grassland_pct": grassland_pct,
        "shrub_pct": shrub_pct,
        "tree_pct": tree_pct,
        "urban_pct": urban_pct,
        "bare_pct": bare_pct,
        "snow_pct": snow_pct,
        "water_mask_grid": mask_17,
        "hidrografia_detectada": hydro_desc,
    }


async def query_planetary_stac(
    lat: float,
    lon: float,
    area_ha: float = 100.0,
) -> Dict[str, Any]:
    """
    Extrae datos geoespaciales REALES de Microsoft Planetary Computer y Nominatim:
    - Copernicus DEM 30m (grilla altimétrica 17x17 real fusionada multi-tile)
    - JRC Global Surface Water (recurrencia histórica 35+ años + estacionalidad real)
    - ESA WorldCover 10m (cobertura real de suelo + detección de agua, costas, ríos, humedales, ciudades)
    - Sentinel-2 L2A (escena reciente: NDVI, NDWI, MNDWI reales)
    - Sentinel-1 RTC (radar SAR VV real en dB)
    - Nominatim (ubicación geográfica real sin coordenadas hardcodeadas)
    """
    half_side_km = max(0.85, min(2.5, math.sqrt(max(20.0, area_ha) / 100.0) * 0.85))
    ctx_side_km = max(3.8, half_side_km * 3.0)
    bbox = get_bbox(lat, lon, buffer_km=half_side_km)
    ctx_bbox = get_bbox(lat, lon, buffer_km=ctx_side_km)

    stac_items: Dict[str, str] = {}
    tile_layers: List[TileLayerInfo] = []

    limits = httpx.Limits(max_connections=24, max_keepalive_connections=12)
    async with httpx.AsyncClient(timeout=12.0, limits=limits) as client:
        # Fase 1: Búsqueda STAC concurrente + geocodificación inversa real + Sentinel-2/1
        dem_task = _search_stac_items(client, "cop-dem-glo-30", ctx_bbox, limit=4)
        jrc_task = _search_stac_items(client, "jrc-gsw", ctx_bbox, limit=4)
        wc_task = _search_stac_items(client, "esa-worldcover", ctx_bbox, limit=6)
        s2_task = _fetch_sentinel2_metrics(client, lat, lon, bbox)
        s1_task = _fetch_sentinel1_metrics(client, lat, lon, bbox)
        nom_task = _reverse_geocode_nominatim(client, lat, lon)

        dem_feats, jrc_feats, wc_raw_feats, s2_metrics, s1_metrics, nom_info = await asyncio.gather(
            dem_task, jrc_task, wc_task, s2_task, s1_task, nom_task
        )
        wc_feats = _select_latest_worldcover_features(wc_raw_feats)

        if dem_feats:
            stac_items["cop-dem-glo-30"] = dem_feats[0]["id"]
        if jrc_feats:
            stac_items["jrc-gsw"] = jrc_feats[0]["id"]
        if wc_feats:
            stac_items["esa-worldcover"] = wc_feats[0]["id"]
        if s2_metrics.get("item_id"):
            stac_items["sentinel-2-l2a"] = str(s2_metrics["item_id"])
        if s1_metrics.get("item_id"):
            stac_items["sentinel-1-rtc"] = str(s1_metrics["item_id"])

        # Fase 2: Descarga concurrente de grillas NPY reales e histogramas a 10m
        p_dem_task = _fetch_merged_grid(
            client, "cop-dem-glo-30", dem_feats, "data", bbox, 17,
            lambda v, m: m > 0 and not math.isnan(v) and -500.0 <= v <= 9000.0,
        )
        c_dem_task = _fetch_merged_grid(
            client, "cop-dem-glo-30", dem_feats, "data", ctx_bbox, 17,
            lambda v, m: m > 0 and not math.isnan(v) and -500.0 <= v <= 9000.0,
        )
        p_jrc_task = _fetch_merged_grid(
            client, "jrc-gsw", jrc_feats, "occurrence", bbox, 33,
            lambda v, m: m > 0 and not math.isnan(v) and 0.0 <= v <= 100.0,
        )
        p_wc_task = _fetch_merged_grid(
            client, "esa-worldcover", wc_feats, "map", bbox, 33,
            lambda v, m: m > 0 and v >= 10.0,
        )
        c_wc_task = _fetch_merged_grid(
            client, "esa-worldcover", wc_feats, "map", ctx_bbox, 33,
            lambda v, m: m > 0 and v >= 10.0,
        )
        wc_hist_task = _fetch_worldcover_histogram(client, wc_feats, bbox)
        jrc_pt_task = _fetch_point_values(
            client, "jrc-gsw", jrc_feats, ["occurrence", "seasonality"], lon, lat
        )
        wc_pt_task = _fetch_point_values(client, "esa-worldcover", wc_feats, ["map"], lon, lat)

        (
            (p_dem_raw, p_dem_mask),
            (c_dem_raw, c_dem_mask),
            (p_jrc_grid, _p_jrc_mask),
            (p_wc_grid, p_wc_mask),
            (c_wc_grid, c_wc_mask),
            wc_hist,
            jrc_pt,
            wc_pt,
        ) = await asyncio.gather(
            p_dem_task, c_dem_task, p_jrc_task, p_wc_task, c_wc_task, wc_hist_task, jrc_pt_task, wc_pt_task
        )

    # Extraer valores puntuales reales JRC y WorldCover
    jrc_center_occ = 0.0
    jrc_season_m = 0
    jrc_center_nodata = False
    if jrc_pt:
        if 0.0 <= jrc_pt[0] <= 100.0:
            jrc_center_occ = round(jrc_pt[0], 1)
        elif jrc_pt[0] >= 250.0:
            jrc_center_nodata = True
        if 0.0 <= jrc_pt[1] <= 12.0:
            jrc_season_m = int(round(jrc_pt[1]))

    center_wc_val: Optional[int] = None
    if wc_pt and wc_pt[0] >= 10.0:
        center_wc_val = int(round(wc_pt[0]))

    # Primero estimamos máscara preliminar 17x17 para rellenar DEM de agua marina nodata
    prelim_water_17 = [[0] * 17 for _ in range(17)]
    c_dem_valid_vals = [
        c_dem_raw[r][c] for r in range(17) for c in range(17) if c_dem_mask[r][c] and c_dem_raw[r][c] is not None
    ]
    near_sea_lvl = (not c_dem_valid_vals) or (min(c_dem_valid_vals) <= 3.0)
    for r17 in range(17):
        sr = min(32, int(round(r17 * 32 / 16.0)))
        for c17 in range(17):
            sc = min(32, int(round(c17 * 32 / 16.0)))
            wc_v = int(p_wc_grid[sr][sc]) if (p_wc_mask[sr][sc] and p_wc_grid[sr][sc] is not None) else None
            jrc_v = p_jrc_grid[sr][sc] if p_jrc_grid[sr][sc] is not None else 0.0
            if wc_v == 80 or (wc_v is None and near_sea_lvl) or jrc_v >= 45.0:
                prelim_water_17[r17][c17] = 2

    has_dem_items = len(dem_feats) > 0
    has_wc_items = len(wc_feats) > 0
    elevation_grid_17, dem_valid_count = _fill_dem_grid_17x17(
        p_dem_raw, p_dem_mask, prelim_water_17, has_dem_items
    )

    hydro_env = _analyze_hydro_and_environment(
        lat=lat,
        lon=lon,
        parcel_bbox=bbox,
        ctx_bbox=ctx_bbox,
        parcel_wc=p_wc_grid,
        parcel_wc_mask=p_wc_mask,
        parcel_jrc=p_jrc_grid,
        parcel_dem_17=elevation_grid_17,
        ctx_wc=c_wc_grid,
        ctx_wc_mask=c_wc_mask,
        ctx_dem=c_dem_raw,
        ctx_dem_mask=c_dem_mask,
        wc_hist=wc_hist,
        center_wc=center_wc_val,
        center_jrc=jrc_center_occ,
        jrc_seasonality_months=jrc_season_m,
        has_dem_items=has_dem_items,
        has_wc_items=has_wc_items,
        nominatim=nom_info,
        ndvi=float(s2_metrics.get("ndvi", 0.0)),
        mndwi=float(s2_metrics.get("mndwi", 0.0)),
    )

    # Estadísticas JRC reales sobre la parcela (33x33)
    jrc_valid = [
        p_jrc_grid[r][c]
        for r in range(33)
        for c in range(33)
        if p_jrc_grid[r][c] is not None and 0.0 <= p_jrc_grid[r][c] <= 100.0
    ]
    jrc_mean = round(sum(jrc_valid) / len(jrc_valid), 1) if jrc_valid else 0.0
    jrc_max = round(max(jrc_valid), 1) if jrc_valid else 0.0
    jrc_wet_frac = sum(1 for v in jrc_valid if v >= 15.0) / max(1, len(jrc_valid))

    if hydro_env["is_open_ocean"] or jrc_center_nodata:
        jrc_occurrence_pct = 100.0 if (hydro_env["is_open_ocean"] or hydro_env["center_is_water"]) else round(max(jrc_center_occ, jrc_mean), 1)
    else:
        jrc_occurrence_pct = round(max(jrc_center_occ, jrc_mean * 0.8 + jrc_max * 0.2 if jrc_max > 0 else jrc_mean), 1)

    jrc_max_extent = bool(jrc_max >= 5.0 or jrc_center_occ >= 5.0 or hydro_env["effective_water_pct"] >= 0.5)
    if hydro_env["is_open_ocean"] and not nom_info.get("country"):
        seasonality = "mar abierto"
    elif jrc_season_m >= 9 or jrc_center_occ >= 70.0 or hydro_env["center_is_water"]:
        seasonality = "permanente"
    elif jrc_season_m >= 3 or jrc_occurrence_pct >= 20.0 or jrc_wet_frac >= 0.15:
        seasonality = "estacional"
    elif jrc_max >= 10.0 or hydro_env["wetland_pct"] >= 10.0:
        seasonality = "efímero"
    else:
        seasonality = "seco"

    center_elev = elevation_grid_17[8][8]
    z_all = [v for row in elevation_grid_17 for v in row]
    z_min_dem = min(z_all) if z_all else 0.0
    z_max_dem = max(z_all) if z_all else 50.0

    # Capas dinámicas STAC con rango DEM ajustado dinámicamente a la parcela
    if jrc_feats:
        tile_layers.append(
            TileLayerInfo(
                name="jrc_water_occurrence",
                collection="jrc-gsw",
                title="Recurrencia Histórica de Agua (JRC 35+ años)",
                tile_url=(
                    f"{PLANETARY_DATA_URL}/item/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@1x"
                    f"?collection=jrc-gsw&item={jrc_feats[0]['id']}&assets=occurrence&colormap_name=jrc-occurrence&nodata=0&format=png"
                ),
                attribution="European Commission JRC / Planetary Computer",
                colormap="jrc-occurrence",
            )
        )
    if dem_feats:
        dem_min_scale = int(max(0, math.floor(z_min_dem - 5)))
        dem_max_scale = int(max(dem_min_scale + 25, math.ceil(z_max_dem + 15)))
        tile_layers.append(
            TileLayerInfo(
                name="copernicus_dem",
                collection="cop-dem-glo-30",
                title=f"Modelo Digital de Elevación (Copernicus DEM 30m · {dem_min_scale}–{dem_max_scale}m)",
                tile_url=(
                    f"{PLANETARY_DATA_URL}/item/tiles/WebMercatorQuad/{{z}}/{{x}}/{{y}}@1x"
                    f"?collection=cop-dem-glo-30&item={dem_feats[0]['id']}&assets=data&colormap_name=terrain"
                    f"&rescale={dem_min_scale},{dem_max_scale}&format=png"
                ),
                attribution="Copernicus / Microsoft Planetary Computer",
                colormap="terrain",
            )
        )

    # Estimar depresión topográfica relativa real del lote (0 = alto/escarpado, 1 = depresión/agua)
    if hydro_env["is_open_ocean"] or hydro_env["center_is_water"]:
        rel_dep = 0.96
    elif hydro_env["is_wetland"]:
        rel_dep = round(min(0.95, 0.58 + hydro_env["wetland_pct"] * 0.004 + hydro_env["effective_water_pct"] * 0.004), 2)
    else:
        center_pos_norm = (center_elev - z_min_dem) / max(0.5, z_max_dem - z_min_dem)
        rel_dep = round(
            max(
                0.02,
                min(
                    0.95,
                    (1.0 - center_pos_norm) * 0.45
                    + (jrc_wet_frac * 0.40)
                    + (jrc_occurrence_pct / 100.0) * 0.35
                    + (0.12 if z_max_dem <= 6.0 and z_max_dem - z_min_dem <= 2.5 else 0.0),
                ),
            ),
            2,
        )

    location_label = nom_info.get("label") or f"Lat {lat:.4f}, Lon {lon:.4f}"
    if hydro_env["is_open_ocean"] and not nom_info.get("country"):
        location_label = "Aguas Oceánicas / Fuera de Costa"

    data_source_mode = "planetary_computer_real" if (dem_feats or wc_feats or jrc_feats) else "degraded_offline"

    lc_breakdown = dict(wc_hist.get("breakdown") or {})
    if not lc_breakdown and (hydro_env["is_open_ocean"] or hydro_env["effective_water_pct"] >= 95.0):
        lc_breakdown = {"Cuerpo de Agua Permanente": round(hydro_env["effective_water_pct"], 1)}

    return {
        "bbox": bbox,
        "half_side_km": half_side_km,
        "location_label": location_label,
        "nominatim": nom_info,
        "elevation_m": round(center_elev, 1),
        "elevation_grid_17": elevation_grid_17,
        "dem_valid_count": dem_valid_count,
        "relative_depression_score": rel_dep,
        "jrc_occurrence_pct": jrc_occurrence_pct,
        "jrc_max_extent": jrc_max_extent,
        "jrc_seasonality": seasonality,
        "jrc_seasonality_months": jrc_season_m,
        "sar_backscatter_db": float(s1_metrics.get("sar_db", -12.0)),
        "sentinel2_ndwi": float(s2_metrics.get("ndwi", -0.2)),
        "sentinel2_mndwi": float(s2_metrics.get("mndwi", -0.3)),
        "sentinel2_ndvi": float(s2_metrics.get("ndvi", 0.0)),
        "satellite_scene_date": s2_metrics.get("date"),
        "land_cover_breakdown": lc_breakdown,
        "hydro_env": hydro_env,
        "stac_items_found": stac_items,
        "tile_layers": tile_layers,
        "data_source_mode": data_source_mode,
    }
