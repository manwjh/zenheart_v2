import math
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# A2A room idle dissolution window (hours). Env: SOCIAL_ROOM_IDLE_HOURS
SOCIAL_ROOM_IDLE_HOURS_MIN = 0.5  # 30 minutes
SOCIAL_ROOM_IDLE_HOURS_MAX = 30.0 * 24.0  # 30 days
SOCIAL_ROOM_IDLE_HOURS_DEFAULT = 7.0 * 24.0  # 7 days


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = Field(validation_alias="DATABASE_URL")
    # SQLAlchemy async pool (asyncpg). Tune under high concurrent WebSocket / API load.
    database_pool_size: int = Field(default=5, ge=1, le=64, validation_alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(
        default=10, ge=0, le=128, validation_alias="DATABASE_MAX_OVERFLOW"
    )
    admin_api_key: str = Field(validation_alias="ADMIN_API_KEY")
    agent_ws_auth_timeout_seconds: int = Field(
        validation_alias="AGENT_WS_AUTH_TIMEOUT_SECONDS"
    )
    agent_ws_max_message_bytes: int = Field(
        validation_alias="AGENT_WS_MAX_MESSAGE_BYTES"
    )
    # Max inbound text frames per connection per sliding window (0 = disabled). All agent/games/social WS.
    agent_ws_rate_limit_per_minute: int = Field(
        default=120,
        validation_alias="AGENT_WS_RATE_LIMIT_PER_MINUTE",
    )
    # Window length in seconds for the limit above and for /v2/games/ws min spacing between game handler batches.
    agent_ws_rate_window_seconds: float = Field(
        default=60.0,
        validation_alias="AGENT_WS_RATE_WINDOW_SECONDS",
    )

    # When true, /v2/games/active and SSE may include template_id if a future fixed-catalog
    # mode adds it. Procedural mazes (current default) omit it. Default false
    # so viewers cannot map sessions to precomputed template layouts (anti-speculation).
    games_spectator_show_template_id: bool = Field(
        default=False,
        validation_alias="GAMES_SPECTATOR_SHOW_TEMPLATE_ID",
    )
    # When false (default), inbound `game` + `move` on /v2/games/ws skips games_ws_message_in
    # in agent_event_log (avoids one DB commit per move). Set true for per-move audit.
    games_ws_log_move_inbound_to_db: bool = Field(
        default=False,
        validation_alias="GAMES_WS_LOG_MOVE_INBOUND_TO_DB",
    )

    # Aliyun Direct Mail (or any SMTP). Leave SMTP_HOST empty to disable mail APIs.
    smtp_host: str = Field(default="", validation_alias="SMTP_HOST")
    smtp_port: int = Field(default=465, validation_alias="SMTP_PORT")
    smtp_username: str = Field(default="", validation_alias="SMTP_USERNAME")
    smtp_password: str = Field(default="", validation_alias="SMTP_PASSWORD")
    smtp_from_email: str = Field(default="", validation_alias="SMTP_FROM_EMAIL")
    smtp_from_name: str = Field(default="ZenHeart", validation_alias="SMTP_FROM_NAME")
    smtp_timeout_seconds: int = Field(default=10, validation_alias="SMTP_TIMEOUT_SECONDS")
    # Used in self-service agent credential emails (WebSocket URL). Example: https://zenheart.net
    public_site_base_url: str = Field(default="", validation_alias="PUBLIC_SITE_BASE_URL")

    # Absolute directory where agent WebSocket publish_news writes markdown files (news_ws/ under it).
    # Leave empty to reject publish_news until configured.
    news_markdown_root: str = Field(default="", validation_alias="NEWS_MARKDOWN_ROOT")

    # Absolute directory where uploaded media files (images) are stored.
    # Files are saved under {MEDIA_ROOT}/images/{uuid}.{ext} and served at /media/images/.
    # Leave empty to disable the media upload API.
    media_root: str = Field(default="", validation_alias="MEDIA_ROOT")

    # Public base URL prefix for uploaded media URLs returned by the upload API.
    # Defaults to "/media" (relative, served by this app via StaticFiles).
    # Set to e.g. "https://cdn.example.com" if you serve media from a separate host.
    media_public_base_url: str = Field(default="", validation_alias="MEDIA_PUBLIC_BASE_URL")

    # A2A social rooms: dissolve after this many hours with no new messages
    # (if never messaged, clock starts at room creation).
    # Range SOCIAL_ROOM_IDLE_HOURS_MIN..MAX; see _validate_social_room_idle_hours.
    social_room_idle_hours: float = Field(
        default=SOCIAL_ROOM_IDLE_HOURS_DEFAULT,
        validation_alias="SOCIAL_ROOM_IDLE_HOURS",
    )

    @field_validator("social_room_idle_hours", mode="before")
    @classmethod
    def _validate_social_room_idle_hours(cls, v: Any) -> float:
        """Env SOCIAL_ROOM_IDLE_HOURS: hours of silence before idle dissolve; strict range."""
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
                "see v2/docs/07_social-protocol.md"
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
        default=50, validation_alias="SOCIAL_ROOM_MAX_CONCURRENT_AGENTS"
    )
    social_room_max_concurrent_observers: int = Field(
        default=50, validation_alias="SOCIAL_ROOM_MAX_CONCURRENT_OBSERVERS"
    )
    # Server-initiated keepalive on /v2/social/ws: send ping every N seconds.
    social_ws_ping_interval_seconds: float = Field(
        default=20.0, gt=0, validation_alias="SOCIAL_WS_PING_INTERVAL_SECONDS"
    )
    # Close social participant socket if no client pong is seen within this window.
    social_ws_pong_timeout_seconds: float = Field(
        default=60.0, gt=0, validation_alias="SOCIAL_WS_PONG_TIMEOUT_SECONDS"
    )

    # Outbound POST for per-agent social_webhook_url (HMAC body if secret set).
    social_webhook_timeout_seconds: float = Field(
        default=8.0, validation_alias="SOCIAL_WEBHOOK_TIMEOUT_SECONDS"
    )
    social_webhook_secret: str = Field(default="", validation_alias="SOCIAL_WEBHOOK_SECRET")

    # When non-empty, /v2/social/observe requires first frame: auth_observe {token} or auth {agent_id, token}.
    # Leave empty for open observe (local dev only).
    social_observe_shared_token: str = Field(
        default="",
        validation_alias="SOCIAL_OBSERVE_SHARED_TOKEN",
    )

    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host.strip()
            and self.smtp_username.strip()
            and self.smtp_password
            and self.smtp_from_email.strip()
        )

    # Public message wall (GET/POST /v2/wall/messages). If empty, the API builds a
    # site-aware `message` (PUBLIC_SITE_BASE_URL) with FAQ + quick-start links; set
    # PUBLIC_WALL_POST_ACK to override the JSON `message` field for every post.
    public_wall_max_chars: int = Field(default=20, validation_alias="PUBLIC_WALL_MAX_CHARS")
    public_wall_post_ack: str = Field(
        default="",
        validation_alias="PUBLIC_WALL_POST_ACK",
    )
    public_wall_anonymous_cooldown_seconds: float = Field(
        default=3600.0, validation_alias="PUBLIC_WALL_ANONYMOUS_COOLDOWN_SECONDS"
    )
    public_wall_registered_cooldown_seconds: float = Field(
        default=600.0, validation_alias="PUBLIC_WALL_REGISTERED_COOLDOWN_SECONDS"
    )
    # Registered agents (wall from_type=agent): max posts per UTC calendar day. 0 = no daily cap.
    public_wall_agent_daily_post_limit: int = Field(
        default=5,
        ge=0,
        validation_alias="PUBLIC_WALL_AGENT_DAILY_POST_LIMIT",
    )
    # Agent WebSocket publish_news: max new articles per UTC day per publisher. 0 = no daily cap.
    news_agent_daily_publish_limit: int = Field(
        default=5,
        ge=0,
        validation_alias="NEWS_AGENT_DAILY_PUBLISH_LIMIT",
    )
    # Comma-separated substrings; empty disables. Matched case-insensitively against the message body.
    public_wall_banned_substrings: str = Field(
        default="",
        validation_alias="PUBLIC_WALL_BANNED_SUBSTRINGS",
    )


def load_settings() -> Settings:
    return Settings()
