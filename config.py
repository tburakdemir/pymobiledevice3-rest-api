from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""

    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "info"

    # Tunnel settings
    tunnel_check_interval: int = 30  # seconds
    tunnel_restart_max_attempts: int = 3
    tunnel_restart_delay: int = 5  # seconds

    # Operation retry settings
    max_retries: int = 3
    retry_delay: int = 2  # seconds

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
