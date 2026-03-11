# config.py – Centralised application settings via Pydantic BaseSettings
# All values are loaded from the .env file (copy .env.example → .env)

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Gemini
    GEMINI_API_KEY: str = "MISSING_GEMINI_KEY"

    # JWT
    SECRET_KEY: str = "insecure-dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # ScaleDown
    SCALEDOWN_API_KEY: str = ""
    SCALEDOWN_API_URL: str = "https://api.scaledown.io/v1/compress"

    # Paths
    DATABASE_URL: str = "sqlite:///./data/pathshala.db"
    CHROMA_DB_PATH: str = "./data/chroma_db"


settings = Settings()
