from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # Velocity check window in seconds
    VELOCITY_WINDOW_SECONDS: int = 60
    VELOCITY_MAX_TRANSACTIONS: int = 10

    model_config = SettingsConfigDict(env_file=".env")


settings = Settings()
