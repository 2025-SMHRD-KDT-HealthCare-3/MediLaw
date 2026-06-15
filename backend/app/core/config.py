from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    ENVIRONMENT: str = "local"
    DATABASE_URL: str = "mysql+pymysql://medilaw:medilaw@localhost:3306/medilaw"
    JWT_SECRET_KEY: str = "change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    OPENAI_API_KEY: str | None = None
    LAW_API_KEY: str | None = None
    UPLOAD_DIR: str = "storage/uploads"
    CORS_ORIGINS: str = "*"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def cors_origins_list(self) -> list[str]:
        if self.CORS_ORIGINS.strip() == "*":
            return ["*"]
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    def validate_runtime_settings(self) -> None:
        """Fail fast only for production-unsafe settings."""
        if self.ENVIRONMENT.lower() in {"prod", "production"} and self.JWT_SECRET_KEY in {
            "change-me",
            "replace-with-secure-secret",
        }:
            raise RuntimeError("JWT_SECRET_KEY must be changed in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
