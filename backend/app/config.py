from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Directory for ephemeral social room CSV state files.
    # Defaults to the OS temp directory when empty.
    social_state_dir: str = Field(default="", validation_alias="SOCIAL_STATE_DIR")

    def smtp_configured(self) -> bool:
        return bool(
            self.smtp_host.strip()
            and self.smtp_username.strip()
            and self.smtp_password
            and self.smtp_from_email.strip()
        )


def load_settings() -> Settings:
    return Settings()
