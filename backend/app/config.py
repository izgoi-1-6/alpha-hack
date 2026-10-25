from dataclasses import dataclass
import os
from pathlib import Path

# Uploaded documents live outside every served path: by default <repository>/var/documents (git- and docker-ignored).
DEFAULT_DOCUMENT_STORAGE = Path(__file__).resolve().parents[2] / 'var' / 'documents'

@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv('DATABASE_URL', 'postgresql+psycopg://credit_route:credit_route_local@localhost:5432/credit_route')
    ui_origin: str = os.getenv('UI_ORIGIN', 'http://localhost:5173')
    demo_mode: bool = os.getenv('DEMO_MODE', 'true').lower() == 'true'
    cookie_secure: bool = os.getenv('COOKIE_SECURE', 'false').lower() == 'true'
    document_storage_dir: str = os.getenv('DOCUMENT_STORAGE_DIR', str(DEFAULT_DOCUMENT_STORAGE))

settings = Settings()
