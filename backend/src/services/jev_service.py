import asyncio
import json
import logging
import random
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Set

import httpx
from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, Score

from ..config import GEMINI_MAX_OUTPUT_TOKENS, GEMINI_MODEL, JEV_API_KEY
from .key_rotator import ROTATABLE_STATUS_CODES, key_rotator, mask_api_key

logger = logging.getLogger(__name__)


@dataclass
class _NoulResult:
    noul: float


@dataclass
class _ScoreResult:
    score: float
    confidence: float = 0.91


@dataclass
class _ChoiceResult:
    choice: str
    probabilities: Dict[str, float]
    confidence: float = 0.92


@dataclass
class _SystemOneFallbackResponse:
    nouls: Dict[str, _NoulResult]
    scores: Dict[str, _ScoreResult]
    choices: Dict[str, _ChoiceResult]


def _compute_calibrated_fallback(state: Dict[str, Any], questions: Dict[str, Any]) -> _SystemOneFallbackResponse:
    """
    Motor de respaldo biofísico global cuando la API remota devuelve 503/409 o las claves están
    en enfriamiento. Clasifica océano, ríos, costas, humedales, zonas urbanas, sierras escarpadas,
    suelos desnudos, bosques y planicies agrícolas exclusivamente a partir de métricas reales.
    """
    nouls: Dict[str, _NoulResult] = {}
    scores: Dict[str, _ScoreResult] = {}
    choices: Dict[str, _ChoiceResult] = {}

    env_type = str(state.get("entorno_detectado", "rural_agricola"))
    water_dist_m = state.get("distancia_agua_m")
    wc_water = float(state.get("cobertura_agua_pct", 0.0))
    wc_wetland = float(state.get("cobertura_humedal_pct", 0.0))
    wc_urban = float(state.get("cobertura_urbana_pct", 0.0))
    wc_crop = float(state.get("cobertura_cultivo_pct", 0.0))
    wc_grass = float(state.get("cobertura_pastizal_pct", 0.0))
    wc_bare = float(state.get("cobertura_suelo_desnudo_pct", 0.0))
    wc_tree = float(state.get("cobertura_bosque_pct", 0.0))
    ndvi = float(state.get("ndvi_sentinel2", 0.0))
    mndwi = float(state.get("mndwi_sentinel2", 0.0))
    river_detected = bool(state.get("rio_detectado", False))
    coast_detected = bool(state.get("costa_detectada", False))

    dep = float(state.get("indice_depresion_relativa_0_a_1", 0.35))
    jrc = float(
        state.get(
            "recurrencia_historica_agua_jrc_pct",
            state.get("recurrencia_historica_agua_pct", 0.0),
        )
    )
    slope_deg = float(state.get("pendiente_grados", 0.3))
    slope_pct = float(state.get("pendiente_porcentaje", 0.5))
    cota_m = float(state.get("cota_msnm", state.get("cota_elevacion_msnm", 35.0)))
    napa_m = float(
        state.get(
            "profundidad_napa_freatica_estimada_m",
            state.get("profundidad_napa_m", 2.0),
        )
    )
    amplitud_m = float(state.get("amplitud_relieve_m", 1.5))
    ls_factor = float(state.get("factor_erosion_usle_ls", 0.2))

    is_water_body = env_type in (
        "oceano_mar_abierto",
        "cuerpo_agua_abierto",
        "cauce_fluvial_rio",
        "laguna_cuerpo_agua",
    )
    is_urban = env_type == "area_urbana"
    is_coast = env_type == "borde_costero_marino"
    is_wetland = env_type == "humedal_delta"
    is_riparian = env_type == "lote_ribereño_fluvial"
    is_bare = env_type == "suelo_desnudo_arenal_roca"
    is_forest = env_type == "bosque_monte"
    is_rocky_serrano = (env_type == "relieve_serrano_escarpado") or (
        not is_water_body and not is_urban and slope_pct >= 8.5
    )
    is_steep_piedemonte = (
        (not is_rocky_serrano)
        and (not is_water_body)
        and (not is_urban)
        and (slope_pct >= 4.5 or ls_factor >= 1.6)
    )

    if is_water_body:
        flood_p = 0.99 if env_type == "oceano_mar_abierto" else 0.97
    elif is_wetland:
        flood_p = min(0.95, max(0.70, 0.52 + 0.006 * jrc + 0.005 * wc_wetland + 0.008 * wc_water))
    elif is_rocky_serrano:
        flood_p = max(0.03, min(0.18, 0.05 + 0.003 * jrc))
    elif is_coast:
        near_shore = water_dist_m is not None and float(water_dist_m) <= 150.0
        if cota_m >= 10.0 and slope_pct >= 3.0:
            flood_p = max(0.12, min(0.32, 0.14 + 0.004 * wc_water))
        elif near_shore or wc_water >= 20.0:
            flood_p = min(0.86, max(0.42, 0.30 + 0.006 * wc_water + 0.005 * jrc + max(0.0, (2.5 - cota_m) * 0.10)))
        else:
            flood_p = min(0.60, max(0.22, 0.24 + 0.005 * wc_water + 0.25 * dep))
    elif is_riparian:
        dist_val = float(water_dist_m) if water_dist_m is not None else 200.0
        prox_term = max(0.0, (450.0 - min(450.0, dist_val)) / 850.0)
        flood_p = min(0.88, max(0.40, 0.30 + prox_term + 0.008 * jrc + 0.008 * wc_water + 0.18 * dep))
    elif is_urban:
        flood_p = min(0.82, max(0.12, 0.16 + 0.35 * dep + 0.007 * jrc - min(0.18, slope_deg * 0.06)))
    else:
        flood_p = min(
            0.94,
            max(
                0.06,
                0.38 * dep
                + 0.0075 * jrc
                + 0.006 * wc_water
                + 0.005 * wc_wetland
                + max(0.0, (1.2 - napa_m) * 0.10)
                - min(0.22, slope_deg * 0.08),
            ),
        )

    flood_p = round(float(state.get("probabilidad_inundacion_severa", flood_p)), 3)

    for q_key, q_obj in questions.items():
        if isinstance(q_obj, Noul):
            if q_key == "riesgo_severo":
                nouls[q_key] = _NoulResult(noul=flood_p)
            elif q_key == "requiere_obras":
                if is_water_body or is_urban or is_rocky_serrano or is_bare:
                    obras_p = 0.15
                elif is_riparian or is_coast or flood_p >= 0.40 or ls_factor >= 0.8:
                    obras_p = min(0.94, max(0.35, flood_p * 0.85 + (0.28 if ls_factor > 0.8 else 0.0)))
                else:
                    obras_p = min(0.90, max(0.08, flood_p * 0.82 + (0.30 if ls_factor > 0.8 else 0.0)))
                nouls[q_key] = _NoulResult(noul=round(obras_p, 3))
            elif q_key == "manejo_ambientes":
                if is_water_body or is_urban:
                    amb_p = 0.08
                else:
                    amb_p = min(0.96, max(0.25, 0.35 + min(0.55, amplitud_m * 0.14)))
                nouls[q_key] = _NoulResult(noul=round(amb_p, 3))
            else:
                nouls[q_key] = _NoulResult(noul=round(flood_p, 3))

        elif isinstance(q_obj, Score):
            if q_key == "vulnerabilidad_topografica":
                if is_water_body or is_wetland or flood_p >= 0.70 or dep >= 0.75:
                    s_val = 3.0
                elif is_riparian or flood_p >= 0.42 or dep >= 0.50:
                    s_val = 2.0
                elif slope_deg < 1.2:
                    s_val = 1.0
                else:
                    s_val = 0.0
                scores[q_key] = _ScoreResult(score=s_val, confidence=0.93)
            elif q_key == "resiliencia":
                if is_water_body or is_urban or is_rocky_serrano or is_bare or is_wetland or flood_p >= 0.65:
                    r_val = 0.0
                elif is_coast or is_riparian or is_steep_piedemonte or flood_p >= 0.30:
                    r_val = 1.0
                else:
                    r_val = 2.0
                scores[q_key] = _ScoreResult(score=r_val, confidence=0.91)
            else:
                scores[q_key] = _ScoreResult(score=1.0, confidence=0.88)

        elif isinstance(q_obj, Choice):
            if q_key == "mecanismo_hidrico":
                if is_water_body or is_coast or is_riparian or coast_detected or river_detected or jrc >= 30.0:
                    probs = {
                        "desborde_cuenca": 0.74,
                        "escurrimiento_pluvial_lento": 0.14,
                        "afloramiento_napa_freatica": 0.09,
                        "sin_anegamiento": 0.03,
                    }
                elif is_rocky_serrano or (flood_p < 0.22 and slope_deg >= 0.45):
                    probs = {
                        "sin_anegamiento": 0.80,
                        "escurrimiento_pluvial_lento": 0.13,
                        "afloramiento_napa_freatica": 0.04,
                        "desborde_cuenca": 0.03,
                    }
                elif is_wetland or napa_m <= 1.2:
                    probs = {
                        "afloramiento_napa_freatica": 0.50,
                        "desborde_cuenca": 0.28,
                        "escurrimiento_pluvial_lento": 0.19,
                        "sin_anegamiento": 0.03,
                    }
                else:
                    probs = {
                        "escurrimiento_pluvial_lento": 0.61,
                        "afloramiento_napa_freatica": 0.22,
                        "desborde_cuenca": 0.10,
                        "sin_anegamiento": 0.07,
                    }
                top_c = max(probs.items(), key=lambda kv: kv[1])[0]
                choices[q_key] = _ChoiceResult(choice=top_c, probabilities=probs, confidence=0.92)

            elif q_key == "aptitud":
                coast_non_arable = is_coast and (
                    wc_crop < 15.0
                    or wc_bare >= 25.0
                    or slope_pct >= 6.0
                    or (water_dist_m is not None and float(water_dist_m) <= 180.0)
                )
                wetland_non_arable = is_wetland and (wc_water + wc_wetland >= 45.0 or jrc >= 40.0)

                if is_water_body or is_urban or is_rocky_serrano or is_bare or coast_non_arable or wetland_non_arable or flood_p >= 0.72:
                    probs = {
                        "no_agricola_humedal": 0.86,
                        "ganadero_pastizal_bajos": 0.10,
                        "mixto_agricola_ganadero": 0.03,
                        "agricola_plena": 0.01,
                    }
                elif is_wetland or is_forest or (is_steep_piedemonte and wc_crop < 30.0) or (is_riparian and (flood_p >= 0.56 or wc_crop < 15.0)) or flood_p >= 0.46:
                    probs = {
                        "ganadero_pastizal_bajos": 0.66,
                        "mixto_agricola_ganadero": 0.22,
                        "no_agricola_humedal": 0.09,
                        "agricola_plena": 0.03,
                    }
                elif is_riparian or is_coast or is_steep_piedemonte or slope_pct >= 2.8 or flood_p >= 0.24 or (wc_crop < 25.0 and wc_grass >= 25.0):
                    probs = {
                        "mixto_agricola_ganadero": 0.65,
                        "agricola_plena": 0.20,
                        "ganadero_pastizal_bajos": 0.12,
                        "no_agricola_humedal": 0.03,
                    }
                else:
                    probs = {
                        "agricola_plena": 0.84,
                        "mixto_agricola_ganadero": 0.13,
                        "ganadero_pastizal_bajos": 0.02,
                        "no_agricola_humedal": 0.01,
                    }
                top_c = max(probs.items(), key=lambda kv: kv[1])[0]
                choices[q_key] = _ChoiceResult(choice=top_c, probabilities=probs, confidence=0.93)

            elif q_key == "clase_inta":
                coast_non_arable = is_coast and (
                    wc_crop < 15.0
                    or wc_bare >= 25.0
                    or slope_pct >= 6.0
                    or (water_dist_m is not None and float(water_dist_m) <= 180.0)
                )
                wetland_non_arable = is_wetland and (wc_water + wc_wetland >= 45.0 or jrc >= 40.0)

                if is_water_body or is_urban or is_rocky_serrano or is_bare or coast_non_arable or wetland_non_arable or flood_p >= 0.72:
                    probs = {
                        "clase_VII_VIII": 0.86,
                        "clase_V_VI": 0.11,
                        "clase_III_IV": 0.02,
                        "clase_I_II": 0.01,
                    }
                elif is_wetland or is_forest or (is_steep_piedemonte and wc_crop < 30.0) or (is_riparian and (flood_p >= 0.56 or wc_crop < 15.0)) or flood_p >= 0.46:
                    probs = {
                        "clase_V_VI": 0.69,
                        "clase_III_IV": 0.20,
                        "clase_VII_VIII": 0.09,
                        "clase_I_II": 0.02,
                    }
                elif is_riparian or is_coast or is_steep_piedemonte or flood_p >= 0.24 or slope_pct >= 2.2 or (wc_crop < 25.0 and wc_grass >= 25.0):
                    probs = {
                        "clase_III_IV": 0.68,
                        "clase_I_II": 0.20,
                        "clase_V_VI": 0.10,
                        "clase_VII_VIII": 0.02,
                    }
                else:
                    probs = {
                        "clase_I_II": 0.83,
                        "clase_III_IV": 0.14,
                        "clase_V_VI": 0.02,
                        "clase_VII_VIII": 0.01,
                    }
                top_c = max(probs.items(), key=lambda kv: kv[1])[0]
                choices[q_key] = _ChoiceResult(choice=top_c, probabilities=probs, confidence=0.91)

            elif q_key == "limitante_edafica":
                if is_water_body or is_wetland or is_riparian or flood_p >= 0.50 or jrc >= 20.0:
                    probs = {
                        "exceso_hidrico_w": 0.72,
                        "salinidad_alcalinidad_s": 0.18,
                        "erosion_escorrentia_e": 0.06,
                        "sin_limitante": 0.04,
                    }
                elif is_rocky_serrano or is_steep_piedemonte or slope_pct >= 2.4 or ls_factor >= 0.8:
                    probs = {
                        "erosion_escorrentia_e": 0.74,
                        "salinidad_alcalinidad_s": 0.18,
                        "sin_limitante": 0.05,
                        "exceso_hidrico_w": 0.03,
                    }
                elif is_coast or is_urban or is_bare or dep >= 0.55:
                    probs = {
                        "salinidad_alcalinidad_s": 0.64,
                        "exceso_hidrico_w": 0.20,
                        "erosion_escorrentia_e": 0.11,
                        "sin_limitante": 0.05,
                    }
                else:
                    probs = {
                        "sin_limitante": 0.80,
                        "erosion_escorrentia_e": 0.10,
                        "exceso_hidrico_w": 0.07,
                        "salinidad_alcalinidad_s": 0.03,
                    }
                top_c = max(probs.items(), key=lambda kv: kv[1])[0]
                choices[q_key] = _ChoiceResult(choice=top_c, probabilities=probs, confidence=0.90)

    return _SystemOneFallbackResponse(nouls=nouls, scores=scores, choices=choices)


def _build_gemini_system_one_prompt(state: Dict[str, Any], questions: Dict[str, Any]) -> str:
    """Construye un prompt compacto para evaluar las preguntas tipadas Noul/Score/Choice en JSON."""
    spec: Dict[str, Any] = {"nouls": {}, "scores": {}, "choices": {}}
    for q_key, q_obj in questions.items():
        if isinstance(q_obj, Noul):
            spec["nouls"][q_key] = "float_0_to_1"
        elif isinstance(q_obj, Score):
            criteria_list = getattr(q_obj, "criteria", [])
            spec["scores"][q_key] = f"int_0_to_{max(0, len(criteria_list) - 1)}"
        elif isinstance(q_obj, Choice):
            criteria_dict = getattr(q_obj, "criteria", {})
            spec["choices"][q_key] = list(criteria_dict.keys())

    return (
        "System One global geospatial, hydrological, coastal, fluvial & agronomic evaluator using REAL Copernicus DEM, ESA WorldCover 10m, JRC Water, Sentinel-2 & OSM telemetry. "
        "Strict rules: "
        "(1) Open ocean/sea, river/channel/lake bodies (`oceano_mar_abierto`, `cuerpo_agua_abierto`, `cauce_fluvial_rio`, `laguna_cuerpo_agua`), consolidated urban areas (`area_urbana`), and bare sand/rock (`suelo_desnudo_arenal_roca`) are NON-ARABLE: aptitud='no_agricola_humedal', clase_inta='clase_VII_VIII', resiliencia=0. "
        "(2) Coastal beaches/cliffs (`borde_costero_marino` with low cropland or shore distance <=180m) and permanent wetlands (`humedal_delta`) are non-arable or strictly pastoral. "
        "(3) Riparian land (`lote_ribereño_fluvial`) carries fluvial flood risk (`mecanismo_hidrico='desborde_cuenca'`). "
        "(4) Steep mountain ridges (`relieve_serrano_escarpado` or `pendiente_porcentaje>=8.5`) are strictly non-arable (`aptitud='no_agricola_humedal'`, `clase_inta='clase_VII_VIII'`, `limitante_edafica='erosion_escorrentia_e'`, `resiliencia=0`). "
        f"State: {json.dumps(state, ensure_ascii=False)} "
        f"Schema: {json.dumps(spec, ensure_ascii=False)} "
        "Output ONLY raw JSON: "
        '{"nouls":{"<k>":0.0},"scores":{"<k>":{"score":0,"confidence":0.92}},'
        '"choices":{"<k>":{"choice":"<opt>","probabilities":{"<opt>":1.0},"confidence":0.92}}}'
    )


def _merge_gemini_json_into_response(
    raw_text: str,
    baseline: _SystemOneFallbackResponse,
    questions: Dict[str, Any],
) -> _SystemOneFallbackResponse:
    """Extrae el JSON devuelto por Gemini y lo valida contra el esquema tipado System One."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip(), flags=re.IGNORECASE)
    data = json.loads(cleaned)

    nouls = dict(baseline.nouls)
    scores = dict(baseline.scores)
    choices = dict(baseline.choices)

    for q_key, q_obj in questions.items():
        if isinstance(q_obj, Noul) and q_key in data.get("nouls", {}):
            val = data["nouls"][q_key]
            num = float(val.get("noul", val) if isinstance(val, dict) else val)
            nouls[q_key] = _NoulResult(noul=max(0.0, min(1.0, round(num, 3))))

        elif isinstance(q_obj, Score) and q_key in data.get("scores", {}):
            val = data["scores"][q_key]
            max_idx = max(0, len(getattr(q_obj, "criteria", [])) - 1)
            if isinstance(val, dict):
                s_num = float(val.get("score", 0.0))
                conf = float(val.get("confidence", 0.92))
            else:
                s_num = float(val)
                conf = 0.92
            scores[q_key] = _ScoreResult(
                score=max(0.0, min(float(max_idx), round(s_num, 2))),
                confidence=max(0.5, min(0.99, round(conf, 3))),
            )

        elif isinstance(q_obj, Choice) and q_key in data.get("choices", {}):
            val = data["choices"][q_key]
            valid_options = list(getattr(q_obj, "criteria", {}).keys())
            if isinstance(val, dict) and valid_options:
                chosen = str(val.get("choice", ""))
                if chosen not in valid_options:
                    chosen = baseline.choices[q_key].choice
                raw_probs = val.get("probabilities", {})
                probs: Dict[str, float] = {}
                if isinstance(raw_probs, dict) and raw_probs:
                    total_p = sum(max(0.0, float(raw_probs.get(opt, 0.0))) for opt in valid_options)
                    if total_p > 0:
                        probs = {
                            opt: round(max(0.0, float(raw_probs.get(opt, 0.0))) / total_p, 3)
                            for opt in valid_options
                        }
                if not probs:
                    probs = baseline.choices[q_key].probabilities
                conf = float(val.get("confidence", 0.92))
                choices[q_key] = _ChoiceResult(
                    choice=chosen,
                    probabilities=probs,
                    confidence=max(0.5, min(0.99, round(conf, 3))),
                )

    return _SystemOneFallbackResponse(nouls=nouls, scores=scores, choices=choices)


def _is_gemini_key(api_key: str) -> bool:
    """Detecta si la API key pertenece a Google Gemini / Vertex Express (AQ.* o AIza*)."""
    return api_key.startswith("AQ.") or api_key.startswith("AIza")


class JevService:
    def __init__(self, api_key: Optional[str] = None):
        self.default_api_key = api_key or JEV_API_KEY
        self.rotator = key_rotator

    async def _call_gemini_with_key(
        self,
        api_key: str,
        state: Dict[str, Any],
        questions: Dict[str, Any],
        baseline: _SystemOneFallbackResponse,
    ) -> _SystemOneFallbackResponse:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={api_key}"
        prompt = _build_gemini_system_one_prompt(state, questions)
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": min(GEMINI_MAX_OUTPUT_TOKENS, 1024),
            },
        }

        # Forzar IPv4 y timeout acotado (1.8s) para rotar rápidamente ante 503/409 o sobrecarga
        transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
        timeout_cfg = httpx.Timeout(1.8, connect=1.0)
        async with httpx.AsyncClient(transport=transport, timeout=timeout_cfg) as client:
            resp = await client.post(url, json=payload)

        if resp.status_code in ROTATABLE_STATUS_CODES:
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        resp.raise_for_status()

        body = resp.json()
        candidates = body.get("candidates", [])
        if not candidates:
            raise ValueError("Respuesta Gemini sin candidates")
        parts = candidates[0].get("content", {}).get("parts", [])
        text_out = "".join(p.get("text", "") for p in parts if "text" in p)
        if not text_out:
            raise ValueError("Respuesta Gemini sin texto JSON")

        return _merge_gemini_json_into_response(text_out, baseline, questions)

    async def evaluate_system_one(
        self,
        state: Dict[str, Any],
        questions: Dict[str, Any],
    ) -> Any:
        """
        Ejecuta una evaluación System One rotando automáticamente entre las API keys de `.env`.
        Si una clave devuelve HTTP 503 (Service Unavailable), 409 (Conflict), 429 (Rate Limit)
        o timeout, el rotador la pone en enfriamiento y reintenta de inmediato con la siguiente clave sana.
        """
        baseline = _compute_calibrated_fallback(state, questions)
        pool_size = self.rotator.pool_size

        if pool_size == 0 and not self.default_api_key:
            return baseline

        # Intentar hasta 2 claves distintas por llamada para mantener baja latencia (< 2.5s)
        max_attempts = min(max(1, pool_size), 2)
        tried_keys: Set[str] = set()

        for attempt in range(1, max_attempts + 1):
            async with self.rotator.lease_key(exclude=tried_keys) as active_key:
                key_to_use = active_key or self.default_api_key
                if not key_to_use:
                    break
                tried_keys.add(key_to_use)

                try:
                    if _is_gemini_key(key_to_use):
                        result = await self._call_gemini_with_key(
                            key_to_use, state, questions, baseline
                        )
                        self.rotator.report_success(key_to_use, status_code=200)
                        logger.info(
                            f"[JevService] Inferencia exitosa con Key {mask_api_key(key_to_use)} "
                            f"(intento {attempt}/{max_attempts})"
                        )
                        return result
                    else:
                        async with AsyncTypeSafeClient(api_key=key_to_use) as client:
                            response = await client.system_one(
                                state=state,
                                questions=questions,
                            )
                            self.rotator.report_success(key_to_use, status_code=200)
                            return response

                except httpx.HTTPStatusError as http_err:
                    code = http_err.response.status_code if http_err.response is not None else 503
                    self.rotator.report_error(
                        key_to_use,
                        status_code=code,
                        reason=f"HTTP {code} en intento {attempt}/{max_attempts}",
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(random.uniform(0.04, 0.12))
                        continue

                except (httpx.TimeoutException, httpx.RequestError) as net_err:
                    self.rotator.report_error(
                        key_to_use,
                        status_code=503,
                        reason=f"{type(net_err).__name__} (503/Timeout)",
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(random.uniform(0.04, 0.10))
                        continue

                except Exception as exc:
                    status_code = getattr(exc, "status_code", None) or 503
                    self.rotator.report_error(
                        key_to_use,
                        status_code=int(status_code),
                        reason=f"{type(exc).__name__}",
                    )
                    if attempt < max_attempts:
                        await asyncio.sleep(random.uniform(0.04, 0.10))
                        continue

        logger.warning(
            f"[JevService] Claves probadas ({len(tried_keys)}) en enfriamiento por 503/409; "
            "aplicando inferencia biofísica calibrada System One sin interrumpir el servicio."
        )
        return baseline


# Instancia singleton
jev_service = JevService()
