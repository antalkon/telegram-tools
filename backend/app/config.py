from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TGT_", extra="ignore")

    admin_password: str = "admin"
    # Used both for JWT signing and for deriving the session-encryption key.
    secret_key: str = "change-me-please-use-a-long-random-string"
    data_dir: Path = Path(__file__).resolve().parent.parent / "data"
    token_ttl_hours: int = 24 * 7
    cookie_secure: bool = False
    # background monitoring loop (disabled in tests)
    scheduler_enabled: bool = True
    # Built frontend (vite build output) served by FastAPI in production.
    frontend_dist: Path = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.data_dir / 'toolkit.db'}"

    @property
    def avatars_dir(self) -> Path:
        return self.data_dir / "avatars"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.avatars_dir.mkdir(parents=True, exist_ok=True)
    s.files_dir.mkdir(parents=True, exist_ok=True)
    return s
