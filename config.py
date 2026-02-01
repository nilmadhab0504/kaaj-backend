from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Lender Match API"
    debug: bool = False

    # Database: set DATABASE_URL in .env to switch between SQLite and PostgreSQL
    # SQLite (default): sqlite+aiosqlite:///./lender_match.db
    # PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname
    database_url: str = "sqlite+aiosqlite:///./lender_match.db"

    # CORS (allow localhost and 127.0.0.1 for dev)
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url.split(":")[0].lower()

    @property
    def is_postgresql(self) -> bool:
        return "postgresql" in self.database_url.split(":")[0].lower()


settings = Settings()
