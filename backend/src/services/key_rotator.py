import logging
import random
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional, Set

from ..config import ENV_PATHS, load_api_keys_from_env

logger = logging.getLogger(__name__)

# Códigos HTTP que disparan rotación inmediata y cooldown temporal de la API key
ROTATABLE_STATUS_CODES: Set[int] = {
    408,  # Request Timeout
    409,  # Conflict / Concurrent contention
    429,  # Too Many Requests / Quota exceeded
    500,  # Internal Server Error
    502,  # Bad Gateway
    503,  # Service Unavailable / Model Overloaded
    504,  # Gateway Timeout
}


def mask_api_key(key: str) -> str:
    """Enmascara una API key para logs y diagnósticos seguros."""
    if not key:
        return "none"
    if len(key) <= 12:
        return key[:4] + "..."
    return f"{key[:10]}...{key[-4:]}"


@dataclass
class KeyState:
    key: str
    index: int
    in_flight: int = 0
    cooldown_until: float = 0.0
    consecutive_errors: int = 0
    total_requests: int = 0
    total_successes: int = 0
    total_errors: int = 0
    last_status_code: Optional[int] = None
    last_error_reason: Optional[str] = None
    last_used_at: float = 0.0

    def is_available(self, now: float) -> bool:
        return now >= self.cooldown_until


class ApiKeyRotator:
    """
    Rotador inteligente de API Keys con:
    - Lectura y recarga automática desde `.env`
    - Balanceo Round-Robin con evasión de colisiones concurrentes (evita HTTP 409 Conflict)
    - Cooldown exponencial con jitter ante errores HTTP 503, 409, 429 y 5xx
    - Failover instantáneo a la siguiente clave sana del pool
    """

    def __init__(self, initial_keys: Optional[List[str]] = None, base_cooldown_sec: float = 15.0):
        self._lock = threading.Lock()
        self._base_cooldown_sec = base_cooldown_sec
        self._states: Dict[str, KeyState] = {}
        self._ordered_keys: List[str] = []
        self._pointer: int = 0
        self._total_rotations: int = 0
        self._last_env_mtime: float = 0.0

        if initial_keys is not None:
            self._sync_keys(initial_keys)
        else:
            self.refresh_from_env(force=True)

    def _get_env_mtime(self) -> float:
        mtimes = [p.stat().st_mtime for p in ENV_PATHS if p.exists()]
        return max(mtimes) if mtimes else 0.0

    def refresh_from_env(self, force: bool = False) -> None:
        """Recarga las claves desde `.env` si el archivo cambió en disco."""
        current_mtime = self._get_env_mtime()
        if not force and current_mtime <= self._last_env_mtime and self._ordered_keys:
            return
        keys = load_api_keys_from_env()
        with self._lock:
            self._last_env_mtime = current_mtime
            self._sync_keys(keys)

    def _sync_keys(self, keys: List[str]) -> None:
        unique_keys: List[str] = []
        for k in keys:
            k_clean = k.strip()
            if k_clean and k_clean not in unique_keys:
                unique_keys.append(k_clean)

        new_states: Dict[str, KeyState] = {}
        for idx, k in enumerate(unique_keys):
            if k in self._states:
                st = self._states[k]
                st.index = idx
                new_states[k] = st
            else:
                new_states[k] = KeyState(key=k, index=idx)

        self._ordered_keys = unique_keys
        self._states = new_states
        if self._ordered_keys:
            self._pointer = self._pointer % len(self._ordered_keys)
        else:
            self._pointer = 0

    @property
    def pool_size(self) -> int:
        self.refresh_from_env()
        return len(self._ordered_keys)

    def acquire_key(self, exclude: Optional[Set[str]] = None) -> Optional[str]:
        """
        Selecciona la siguiente API key óptima usando Round-Robin:
        1. Prioriza claves fuera de cooldown y sin peticiones en vuelo (in_flight == 0) para evitar 409/503.
        2. Si todas las disponibles tienen peticiones en vuelo, elige la de menor in_flight.
        3. Si todas están en cooldown, elige la que tenga el cooldown más próximo a expirar.
        """
        self.refresh_from_env()
        with self._lock:
            n = len(self._ordered_keys)
            if n == 0:
                return None

            exclude_set = exclude or set()
            now = time.monotonic()

            candidates = [
                self._ordered_keys[(self._pointer + offset) % n]
                for offset in range(n)
            ]
            # Filtrar excluidas en este ciclo de reintento si hay alternativas
            non_excluded = [k for k in candidates if k not in exclude_set]
            search_pool = non_excluded if non_excluded else candidates

            # 1. Claves sanas (sin cooldown) y libres (in_flight == 0)
            free_healthy = [
                k for k in search_pool
                if self._states[k].is_available(now) and self._states[k].in_flight == 0
            ]
            if free_healthy:
                chosen = free_healthy[0]
            else:
                # 2. Claves sanas con menor cantidad de peticiones concurrentes en vuelo
                healthy = [k for k in search_pool if self._states[k].is_available(now)]
                if healthy:
                    chosen = min(healthy, key=lambda k: self._states[k].in_flight)
                else:
                    # 3. Todas en cooldown: elegir la que se libere más pronto
                    chosen = min(search_pool, key=lambda k: self._states[k].cooldown_until)

            st = self._states[chosen]
            st.in_flight += 1
            st.total_requests += 1
            st.last_used_at = time.time()

            # Avanzar puntero round-robin al siguiente índice después de la clave elegida
            self._pointer = (st.index + 1) % n
            self._total_rotations += 1
            return chosen

    def release_key(self, key: Optional[str]) -> None:
        if not key:
            return
        with self._lock:
            st = self._states.get(key)
            if st and st.in_flight > 0:
                st.in_flight -= 1

    def report_success(self, key: str, status_code: int = 200) -> None:
        """Registra éxito en una clave y limpia su contador de fallos consecutivos."""
        with self._lock:
            st = self._states.get(key)
            if not st:
                return
            st.consecutive_errors = 0
            st.cooldown_until = 0.0
            st.total_successes += 1
            st.last_status_code = status_code
            st.last_error_reason = None

    def report_error(
        self,
        key: str,
        status_code: Optional[int] = None,
        reason: str = "",
        cooldown_override_sec: Optional[float] = None,
    ) -> float:
        """
        Penaliza temporalmente una clave que devolvió 503, 409, 429 o timeout,
        sacándola de rotación durante el período de enfriamiento (exponential backoff + jitter).
        """
        with self._lock:
            st = self._states.get(key)
            if not st:
                return 0.0

            st.consecutive_errors += 1
            st.total_errors += 1
            st.last_status_code = status_code
            st.last_error_reason = reason or f"HTTP {status_code}"

            if cooldown_override_sec is not None:
                cooldown = cooldown_override_sec
            else:
                # Backoff exponencial con jitter: 15s, 30s, 60s, 120s
                multiplier = min(8, 2 ** (st.consecutive_errors - 1))
                jitter = random.uniform(0.5, 3.0)
                cooldown = (self._base_cooldown_sec * multiplier) + jitter

            st.cooldown_until = time.monotonic() + cooldown
            logger.warning(
                f"[KeyRotator] Key #{st.index + 1} ({mask_api_key(key)}) recibió {st.last_error_reason}. "
                f"En cooldown por {cooldown:.1f}s (errores consecutivos: {st.consecutive_errors})."
            )
            return cooldown

    @asynccontextmanager
    async def lease_key(self, exclude: Optional[Set[str]] = None) -> AsyncIterator[Optional[str]]:
        """Context manager asíncrono que adquiere y libera una API key garantizando conteo in_flight."""
        key = self.acquire_key(exclude=exclude)
        try:
            yield key
        finally:
            self.release_key(key)

    def get_status(self) -> Dict[str, Any]:
        """Devuelve telemetría en vivo del pool de claves para `/api/health`."""
        self.refresh_from_env()
        with self._lock:
            now = time.monotonic()
            keys_info = []
            healthy_count = 0
            for k in self._ordered_keys:
                st = self._states[k]
                avail = st.is_available(now)
                if avail:
                    healthy_count += 1
                remaining_cd = max(0.0, round(st.cooldown_until - now, 1))
                keys_info.append({
                    "slot": st.index + 1,
                    "masked_key": mask_api_key(k),
                    "status": "healthy" if avail else "cooldown",
                    "in_flight": st.in_flight,
                    "cooldown_remaining_sec": remaining_cd,
                    "total_requests": st.total_requests,
                    "total_successes": st.total_successes,
                    "total_errors": st.total_errors,
                    "last_status_code": st.last_status_code,
                    "last_error": st.last_error_reason,
                })

            return {
                "total_unique_keys": len(self._ordered_keys),
                "healthy_keys": healthy_count,
                "cooldown_keys": len(self._ordered_keys) - healthy_count,
                "next_slot": (self._pointer + 1) if self._ordered_keys else None,
                "total_rotations": self._total_rotations,
                "keys": keys_info,
            }


# Singleton global del rotador de claves
key_rotator = ApiKeyRotator()

