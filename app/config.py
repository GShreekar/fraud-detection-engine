from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"

    # --- Redis ---
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379

    # --- Neo4j ---
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"

    # --- Velocity checks (Phase 3) ---
    # Sliding window duration in seconds
    VELOCITY_WINDOW_SECONDS: int = 60
    # Maximum transactions within the window before a score is returned
    VELOCITY_MAX_TRANSACTIONS: int = 10

    # --- RulesService (Phase 2) ---
    # Transactions above this USD amount trigger the high-amount rule
    HIGH_AMOUNT_THRESHOLD: float = 1000.0
    # ISO 3166-1 alpha-2 country codes considered high-risk
    HIGH_RISK_COUNTRIES: list[str] = ["NG", "GH", "KP", "IR", "SY", "YE", "SO", "MM"]
    # Accounts younger than this many days are considered new (higher risk)
    RULE_NEW_ACCOUNT_DAYS: int = 30
    # Merchant categories considered high-risk for fraud
    HIGH_RISK_MERCHANTS: list[str] = ["crypto", "gambling", "gift_cards", "wire_transfer"]

    # --- GraphService (Phase 4) ---
    # Minimum number of distinct users on the same device before scoring begins
    GRAPH_SHARED_DEVICE_THRESHOLD: int = 2
    # Minimum number of distinct users on the same IP before scoring begins
    GRAPH_IP_CLUSTER_THRESHOLD: int = 3

    # --- FraudEngine score weights (Phase 5) — must sum to 1.0 ---
    WEIGHT_RULES: float = 0.30
    WEIGHT_VELOCITY: float = 0.35
    WEIGHT_GRAPH: float = 0.35

    model_config = SettingsConfigDict(env_file=".env")

    @model_validator(mode="after")
    def _weights_must_sum_to_one(self) -> "Settings":
        """Validate that the three score weights sum to exactly 1.0."""
        total = round(self.WEIGHT_RULES + self.WEIGHT_VELOCITY + self.WEIGHT_GRAPH, 10)
        if abs(total - 1.0) > 1e-9:
            raise ValueError(
                f"WEIGHT_RULES + WEIGHT_VELOCITY + WEIGHT_GRAPH must equal 1.0, got {total}"
            )
        return self


settings = Settings()
