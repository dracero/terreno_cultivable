import os
import re
from pathlib import Path
from typing import List
from dotenv import load_dotenv

# Search for .env in parent root dir and backend dir
backend_dir = Path(__file__).resolve().parent.parent
parent_dir = backend_dir.parent

ENV_PATHS = [parent_dir / ".env", backend_dir / ".env"]

def reload_env_files() -> None:
    """Recarga los archivos .env desde la raíz del proyecto y desde backend/."""
    loaded = False
    for env_path in ENV_PATHS:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            loaded = True
    if not loaded:
        load_dotenv(override=True)

reload_env_files()

def parse_key_string(raw: str) -> List[str]:
    """Divide una cadena de API keys separadas por comas, punto y coma o saltos de línea."""
    if not raw:
        return []
    parts = re.split(r"[,;\n\r]+", raw)
    cleaned: List[str] = []
    for part in parts:
        key = part.strip().strip("'").strip('"').strip()
        if key and key not in cleaned:
            cleaned.append(key)
    return cleaned

def load_api_keys_from_env() -> List[str]:
    """
    Obtiene y deduplica todas las API keys configuradas en el archivo .env.
    Soporta listas separadas por coma en GEMINI_API_KEY, GEMINI_API_KEYS,
    GOOGLE_API_KEY, JEV_API_KEY, TYPESAFE_API_KEY y variables numeradas (GEMINI_API_KEY_1, etc.).
    """
    reload_env_files()
    keys: List[str] = []

    env_var_names = [
        "GEMINI_API_KEY",
        "GEMINI_API_KEYS",
        "GOOGLE_API_KEY",
        "JEV_API_KEY",
        "TYPESAFE_API_KEY",
    ]
    for var_name in env_var_names:
        for k in parse_key_string(os.getenv(var_name, "")):
            if k not in keys:
                keys.append(k)

    # También soportar GEMINI_API_KEY_1, GEMINI_API_KEY_2, etc.
    for env_k, env_v in sorted(os.environ.items()):
        if re.match(r"^(GEMINI|GOOGLE|JEV|TYPESAFE)_API_KEY_\d+$", env_k):
            for k in parse_key_string(env_v):
                if k not in keys:
                    keys.append(k)

    return keys

API_KEYS_LIST: List[str] = load_api_keys_from_env()
JEV_API_KEY: str = API_KEYS_LIST[0] if API_KEYS_LIST else ""
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()
GEMINI_MAX_OUTPUT_TOKENS: int = int(os.getenv("GEMINI_MAX_OUTPUT_TOKENS", "32768"))
HF_TOKEN: str = os.getenv("HF_TOKEN", "").strip()
HUGGINGFACE_EMBEDDING_MODEL: str = os.getenv("HUGGINGFACE_EMBEDDING_MODEL", "Xenova/all-MiniLM-L6-v2").strip()
OPA_BIN_PATH: str = os.getenv("OPA_BIN_PATH", "").strip()

PLANETARY_STAC_URL: str = os.getenv("PLANETARY_STAC_URL", "https://planetarycomputer.microsoft.com/api/stac/v1")
PLANETARY_DATA_URL: str = os.getenv("PLANETARY_DATA_URL", "https://planetarycomputer.microsoft.com/api/data/v1")
PORT: int = int(os.getenv("PORT", "8000"))
HOST: str = os.getenv("HOST", "0.0.0.0")

# Ensure TYPESAFE_API_KEY is available in os.environ for SDK default lookup
if JEV_API_KEY and not os.getenv("TYPESAFE_API_KEY"):
    os.environ["TYPESAFE_API_KEY"] = JEV_API_KEY
