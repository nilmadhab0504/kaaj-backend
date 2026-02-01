from pydantic import PrivateAttr
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Lender Match API"
    debug: bool = False

    database_url: str = "sqlite+aiosqlite:///./lender_match.db"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    _is_sqlite: bool = PrivateAttr(default=False)
    _is_postgresql: bool = PrivateAttr(default=False)

    def model_post_init(self, __context: object) -> None:
        _scheme = self.database_url.split(":")[0].lower()
        object.__setattr__(self, "_is_sqlite", "sqlite" in _scheme)
        object.__setattr__(self, "_is_postgresql", "postgresql" in _scheme)

    @property
    def is_sqlite(self) -> bool:
        return self._is_sqlite

    @property
    def is_postgresql(self) -> bool:
        return self._is_postgresql


settings = Settings()
