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
    admin_api_key: str = Field(validation_alias="ADMIN_API_KEY")
    agent_ws_auth_timeout_seconds: int = Field(
        validation_alias="AGENT_WS_AUTH_TIMEOUT_SECONDS"
    )
    agent_ws_max_message_bytes: int = Field(
        validation_alias="AGENT_WS_MAX_MESSAGE_BYTES"
    )
    agent_ws_rate_limit_per_minute: int = Field(
        validation_alias="AGENT_WS_RATE_LIMIT_PER_MINUTE"
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
                "see v2/docs/social-protocol.md"
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

    # Outbound POST for per-agent social_webhook_url (HMAC body if secret set).
    social_webhook_timeout_seconds: float = Field(
        default=8.0, validation_alias="SOCIAL_WEBHOOK_TIMEOUT_SECONDS"
    )
    social_webhook_secret: str = Field(default="", validation_alias="SOCIAL_WEBHOOK_SECRET")

    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host.strip()
            and self.smtp_username.strip()
            and self.smtp_password
            and self.smtp_from_email.strip()
        )


def load_settings() -> Settings:
    return Settings()
