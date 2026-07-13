from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    LOGGING_LEVEL: str = "INFO"
    FORPSI_USER: str
    FORPSI_PASS: str
    FORPSI_SITE: str = "admin.forpsi.hu"
    EXPORTER_PORT: int = 9123
    CACHE_TTL: int = 3600

    class Config:
        env_file = ".env"

settings = Settings()