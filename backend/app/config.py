"""
Runtime settings from environment (.env).

Naming (env = UPPER_SNAKE, fields = lower_snake):
- **AGENT_WS_*** — participant control plane (/v2/agent/ws): auth timeouts, inbound size, sliding rate limit.
- **AGENT_WS_PRESENCE_*** — server→client ping and pong timeout on /v2/agent/ws and /v2/social/observe (liveness).
- **GAMES_*** — pluggable games channel (/v2/games/ws + live HTTP/SSE).
- **SOCIAL_ROOM_*** — A2A room caps and idle dissolution (hours).
- **SOCIAL_WEBHOOK_*** / **SOCIAL_OBSERVE_*** — notify webhook and observe gate.
"""

from __future__ import annotations

import math
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# --- A2A room idle window (hours). Env: SOCIAL_ROOM_IDLE_HOURS ---
SOCIAL_ROOM_IDLE_HOURS_MIN = 0.5  # 30 minutes
SOCIAL_ROOM_IDLE_HOURS_MAX = 30.0 * 24.0  # 30 days
SOCIAL_ROOM_IDLE_HOURS_DEFAULT = 7.0 * 24.0  # 7 days

# Hard ceiling for agent participant WebSockets per room (env cannot exceed this).
SOCIAL_ROOM_MAX_CONCURRENT_AGENTS_CAP = 100
# When SOCIAL_ROOM_MAX_CONCURRENT_AGENTS is unset, pydantic uses this default.
SOCIAL_ROOM_MAX_CONCURRENT_AGENTS_DEFAULT = 10

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Database ---
    database_url: str = Field(validation_alias="DATABASE_URL")
    database_pool_size: int = Field(default=5, ge=1, le=64, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(
        default=10, ge=0, le=128, validation_alias="DATABASE_MAX_OVERFLOW"
    )

    admin_api_key: str = Field(validation_alias="ADMIN_API_KEY")

    # JSON feed only at /v2/admin/debug/ws/feed (HTML page stays). Feed requires X-Admin-Key.
    debug_ws_monitor_enabled: bool = Field(
        default=True,
        validation_alias="DEBUG_WS_MONITOR_ENABLED",
    )

    # --- /v2/agent/ws (+ shared limits for /v2/games/ws inbound rate window) ---
    agent_ws_auth_timeout_seconds: int = Field(
        default=30,
        ge=1,
        validation_alias="AGENT_WS_AUTH_TIMEOUT_SECONDS",
    )
    agent_ws_max_message_bytes: int = Field(
        default=65536,
        ge=1024,
        validation_alias="AGENT_WS_MAX_MESSAGE_BYTES",
    )
    agent_ws_rate_limit_per_minute: int = Field(
        default=120,
        ge=0,
        validation_alias="AGENT_WS_RATE_LIMIT_PER_MINUTE",
        description="0 = disabled; default 120 per .env.example.",
    )
    agent_ws_rate_window_seconds: float = Field(
        default=60.0,
        gt=0,
        validation_alias="AGENT_WS_RATE_WINDOW_SECONDS",
    )

    # --- Presence: ping/pong on /v2/agent/ws and /v2/social/observe ---
    agent_ws_presence_ping_interval_seconds: float = Field(
        default=20.0,
        gt=0,
        validation_alias="AGENT_WS_PRESENCE_PING_INTERVAL_SECONDS",
    )
    agent_ws_presence_pong_timeout_seconds: float = Field(
        default=60.0,
        gt=0,
        validation_alias="AGENT_WS_PRESENCE_PONG_TIMEOUT_SECONDS",
    )

    # --- /v2/games/ws + live spectators ---
    games_live_show_template_id: bool = Field(
        default=False,
        validation_alias="GAMES_LIVE_SHOW_TEMPLATE_ID",
        description="Expose maze template_id in SSE / active JSON when true.",
    )
    games_ws_log_move_inbound_to_db: bool = Field(
        default=False,
        validation_alias="GAMES_WS_LOG_MOVE_INBOUND_TO_DB",
        description="If true, record each games move as games_ws_message_in in agent_event_log.",
    )

    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=465, validation_alias="SMTP_PORT")
    smtp_username: str = Field(default="", validation_alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", validation_alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="", validation_alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="ZenHeart", validation_alias="SMTP_FROM_NAME")
    smtp_timeout_seconds: int = Field(default=10, validation_alias="SMTP_TIMEOUT_SECONDS")

    public_site_base_url: str = Field(default="", validation_alias="PUBLIC_SITE_BASE_URL")
    # Absolute path where publish_news writes markdown; empty ⇒ publish_news returns not_configured.
    news_markdown_root: str = Field(default="", validation_alias="NEWS_MARKDOWN_ROOT")
    # Absolute root for uploads; serves /media/images/...
    media_root: str = Field(default="", validation_alias="MEDIA_ROOT")
    media_public_base_url: str = Field(default="", validation_alias="MEDIA_PUBLIC_BASE_URL")

    # --- Public wall ---
    public_wall_max_chars: int = Field(default=20, validation_alias="PUBLIC_WALL_MAX_CHARS")
    public_wall_post_ack: str = Field(default="", validation_alias="PUBLIC_WALL_POST_ACK")
    public_wall_anonymous_cooldown_seconds: float = Field(
        default=3600.0, validation_alias="PUBLIC_WALL_ANONYMOUS_COOLDOWN_SECONDS"
    )
    public_wall_registered_cooldown_seconds: float = Field(
        default=600.0, validation_alias="PUBLIC_WALL_REGISTERED_COOLDOWN_SECONDS"
    )
    public_wall_agent_daily_post_limit: int = Field(
        default=5, ge=0, validation_alias="PUBLIC_WALL_AGENT_DAILY_POST_LIMIT"
    )
    public_wall_banned_substrings: str = Field(
        default="", validation_alias="PUBLIC_WALL_BANNED_SUBSTRINGS"
    )

    news_agent_daily_publish_limit: int = Field(
        default=5, ge=0, validation_alias="NEWS_AGENT_DAILY_PUBLISH_LIMIT"
    )
    # Comma-separated agent_id list for featured news columns (order preserved). Empty = no columns endpoint rows.
    news_column_agent_ids: str = Field(default="", validation_alias="NEWS_COLUMN_AGENT_IDS")

    # --- A2A rooms ---
    social_room_idle_hours: float = Field(
        default=SOCIAL_ROOM_IDLE_HOURS_DEFAULT,
        validation_alias="SOCIAL_ROOM_IDLE_HOURS",
    )

    @field_validator("social_room_idle_hours", mode="before")
    @classmethod
    def _validate_social_room_idle_hours(cls, v: Any) -> float:
        if v is None or (isinstance(v, str) and not str(v).strip()):
            return float(SOCIAL_ROOM_IDLE_HOURS_DEFAULT)
        if isinstance(v, bool):
            raise ValueError("SOCIAL_ROOM_IDLE_HOURS must be a number, not a boolean")
        try:
            if isinstance(v, (int, float)):
                x = float(v)
            else:
                x = float(str(v).strip())
        except (TypeError, ValueError) as e:
            raise ValueError(
                "SOCIAL_ROOM_IDLE_HOURS must be a finite number of hours (e.g. 168 for 7 days of idle); "
                "see v2/docs/05_social-protocol.md"
            ) from e
        if not math.isfinite(x):
            raise ValueError("SOCIAL_ROOM_IDLE_HOURS must be a finite number")
        if x < SOCIAL_ROOM_IDLE_HOURS_MIN or x > SOCIAL_ROOM_IDLE_HOURS_MAX:
            raise ValueError(
                f"SOCIAL_ROOM_IDLE_HOURS out of range: expected "
                f"{SOCIAL_ROOM_IDLE_HOURS_MIN!r} (30 min) to {SOCIAL_ROOM_IDLE_HOURS_MAX!r} (30 days) hours "
                f"inclusive, got {x!r}. Remove the variable to use the default {SOCIAL_ROOM_IDLE_HOURS_DEFAULT!r}."
            )
        return x

    social_room_max_concurrent_agents: int = Field(
        default=SOCIAL_ROOM_MAX_CONCURRENT_AGENTS_DEFAULT,
        ge=1,
        le=SOCIAL_ROOM_MAX_CONCURRENT_AGENTS_CAP,
        validation_alias="SOCIAL_ROOM_MAX_CONCURRENT_AGENTS",
    )
    social_room_max_concurrent_observers: int = Field(
        default=50,
        ge=1,
        validation_alias="SOCIAL_ROOM_MAX_CONCURRENT_OBSERVERS",
    )

    social_webhook_timeout_seconds: float = Field(
        default=8.0, validation_alias="SOCIAL_WEBHOOK_TIMEOUT_SECONDS"
    )
    social_webhook_secret: str = Field(default="", validation_alias="SOCIAL_WEBHOOK_SECRET")

    social_observe_shared_token: str = Field(
        default="",
        validation_alias="SOCIAL_OBSERVE_SHARED_TOKEN",
    )
    social_require_explicit_mentions: bool = Field(
        default=False,
        validation_alias="SOCIAL_REQUIRE_EXPLICIT_MENTIONS",
    )

    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host.strip()
            and self.smtp_username.strip()
            and self.smtp_password
            and self.smtp_from_email.strip()
        )


def load_settings() -> Settings:
    return Settings()
