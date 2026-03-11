from urllib.parse import urlparse

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_ENV: str = "development"

    # --- Redis ---
    # Accepts either REDIS_HOST+REDIS_PORT or a full REDIS_URL (e.g. redis://host:6379)
    REDIS_URL: str | None = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    REDIS_DB: int = 0
    REDIS_SOCKET_TIMEOUT: int = 5
    REDIS_MAX_CONNECTIONS: int = 50

    # --- Neo4j ---
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str = "password"
    NEO4J_DATABASE: str = "neo4j"
    NEO4J_MAX_CONNECTION_POOL_SIZE: int = 50
    NEO4J_CONNECTION_TIMEOUT: int = 5

    # --- Velocity checks (Phase 3) ---
    # Sliding window duration in seconds
    VELOCITY_WINDOW_SECONDS: int = 60
    # Maximum transactions within the window before a score is returned (per dimension)
    VELOCITY_MAX_TRANSACTIONS: int = 10
    VELOCITY_MAX_TRANSACTIONS_USER: int = 10
    VELOCITY_MAX_TRANSACTIONS_IP: int = 10
    VELOCITY_MAX_TRANSACTIONS_DEVICE: int = 10
    # Country-change detection TTL (24 hours)
    VELOCITY_COUNTRY_CACHE_TTL_SECONDS: int = 86400
    # Amount spike detection
    VELOCITY_AMOUNT_SPIKE_MULTIPLIER: float = 5.0
    VELOCITY_AMOUNT_HISTORY_SIZE: int = 20

    # --- RulesService (Phase 2) ---
    # Transactions above this USD amount trigger the high-amount rule
    HIGH_AMOUNT_THRESHOLD: float = 1000.0
    # ISO 3166-1 alpha-2 country codes considered high-risk
    HIGH_RISK_COUNTRIES: list[str] = [
        "NG", "GH", "KP", "IR", "SY", "YE", "SO", "MM",
        "CN", "KE",
    ]
    # Accounts younger than this many days are considered new (higher risk)
    RULE_NEW_ACCOUNT_DAYS: int = 30
    # Merchant categories considered high-risk for fraud
    HIGH_RISK_MERCHANTS: list[str] = [
        "crypto", "gambling", "gift_cards", "wire_transfer",
        "crypto_exchange", "luxury_goods",
    ]

    # --- GraphService (Phase 4) ---
    # Minimum number of distinct users on the same device before scoring begins
    GRAPH_SHARED_DEVICE_THRESHOLD: int = 2
    # Minimum number of distinct users on the same IP before scoring begins
    GRAPH_IP_CLUSTER_THRESHOLD: int = 3
    # Merchant ring detection — distinct users at the same merchant
    GRAPH_MERCHANT_RING_THRESHOLD: int = 5
    GRAPH_MERCHANT_RING_WINDOW_HOURS: int = 24
    # Rolling time-window filter to ignore stale graph signals (days)
    GRAPH_TIME_WINDOW_DAYS: int = 30

    # --- FraudEngine score weights (Phase 5) — must sum to 1.0 ---
    WEIGHT_RULES: float = 0.50
    WEIGHT_VELOCITY: float = 0.25
    WEIGHT_GRAPH: float = 0.25

    model_config = SettingsConfigDict(env_file=".env")

    @model_validator(mode="after")
    def _parse_redis_url(self) -> "Settings":
        """Extract REDIS_HOST and REDIS_PORT from REDIS_URL when provided."""
        if self.REDIS_URL is not None:
            parsed = urlparse(self.REDIS_URL)
            if parsed.hostname:
                self.REDIS_HOST = parsed.hostname
            if parsed.port:
                self.REDIS_PORT = parsed.port
        return self

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
