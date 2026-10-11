import os
from pathlib import Path
from dotenv import load_dotenv

# Search for .env in current backend dir or parent dir
backend_dir = Path(__file__).resolve().parent.parent
parent_dir = backend_dir.parent

if (backend_dir / ".env").exists():
    load_dotenv(backend_dir / ".env")
elif (parent_dir / ".env").exists():
    load_dotenv(parent_dir / ".env")
else:
    load_dotenv()

JEV_API_KEY = os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY") or ""
PLANETARY_STAC_URL = os.getenv("PLANETARY_STAC_URL", "https://planetarycomputer.microsoft.com/api/stac/v1")
PLANETARY_DATA_URL = os.getenv("PLANETARY_DATA_URL", "https://planetarycomputer.microsoft.com/api/data/v1")
PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")

# Ensure TYPESAFE_API_KEY is available in os.environ for SDK default lookup
if JEV_API_KEY and not os.getenv("TYPESAFE_API_KEY"):
    os.environ["TYPESAFE_API_KEY"] = JEV_API_KEY
