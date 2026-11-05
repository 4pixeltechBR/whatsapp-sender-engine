"""
Application configuration and directory management for WhatsApp Sender Engine.
"""

from pathlib import Path
from typing import List
import os

class Settings:
    # Caminhos Base e de Dados
    BASE_DIR: Path = Path(__file__).resolve().parent.parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    SESSION_DIR: Path = DATA_DIR / "session"
    UPLOADS_DIR: Path = DATA_DIR / "uploads"
    REPORTS_DIR: Path = DATA_DIR / "reports"
    STATIC_DIR: Path = BASE_DIR / "app" / "static"

    # Servidor Local Desktop
    HOST: str = os.getenv("WSE_HOST", "127.0.0.1")
    PORT: int = int(os.getenv("WSE_PORT", "8765"))
    APP_NAME: str = "WhatsApp Sender Engine"
    DEBUG: bool = os.getenv("WSE_DEBUG", "false").lower() in ("true", "1", "yes")

    # Limites e Otimização de Memória
    MAX_UPLOAD_SIZE_MB: int = 50
    STREAMING_CHUNK_SIZE: int = 1000
    MAX_PREVIEW_ROWS: int = 500

    # Padrões Anti-Ban de Disparo (Milestone 3)
    DEFAULT_JITTER_MIN: float = 10.0
    DEFAULT_JITTER_MAX: float = 25.0
    BATCH_SIZE: int = 20
    BATCH_PAUSE_SECONDS: float = 120.0

    @classmethod
    def ensure_directories(cls) -> List[Path]:
        """Garante que todos os diretórios operacionais persistentes existam no disco."""
        directories = [
            cls.DATA_DIR,
            cls.SESSION_DIR,
            cls.UPLOADS_DIR,
            cls.REPORTS_DIR,
            cls.STATIC_DIR,
        ]
        created = []
        for d in directories:
            if not d.exists():
                d.mkdir(parents=True, exist_ok=True)
                created.append(d)
        return created

settings = Settings()
# Garante a existência dos diretórios no momento do import
settings.ensure_directories()
