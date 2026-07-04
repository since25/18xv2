from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="dev", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    database_url: str = Field(default="sqlite:///./data/storage_organizer.db", alias="DATABASE_URL")

    # 115 Open API credentials
    app_id: str | None = Field(default=None, alias="APP_ID")
    app_key: str | None = Field(default=None, alias="APP_KEY")
    app_secret: str | None = Field(default=None, alias="APP_SECRET")
    app_redirect_uri: str | None = Field(default=None, alias="APP_REDIRECT_URI")
    app_auth_code: str | None = Field(default=None, alias="APP_AUTH_CODE")

    # Initial token seed — live tokens come from data/tokens.json (see TokenStore)
    access_token: str | None = Field(default=None, alias="ACCESS_TOKEN")
    refresh_token: str | None = Field(default=None, alias="REFRESH_TOKEN")

    # Execution safety
    test_allowed_root_ids: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="TEST_ALLOWED_ROOT_IDS")
    test_allowed_path_prefixes: Annotated[list[str], NoDecode] = Field(
        default_factory=list, alias="TEST_ALLOWED_PATH_PREFIXES"
    )
    default_dry_run: bool = Field(default=True, alias="DEFAULT_DRY_RUN")

    # Strategy
    rules_file: str = Field(default="examples/rules.yaml", alias="RULES_FILE")
    strategy_source: str = Field(default="auto", alias="STRATEGY_SOURCE")

    # 115 API tuning
    api_min_interval_ms: int = Field(default=800, alias="API_MIN_INTERVAL_MS")
    api_max_retries: int = Field(default=2, alias="API_MAX_RETRIES")
    api_retry_backoff_ms: int = Field(default=1200, alias="API_RETRY_BACKOFF_MS")
    api_refresh_cooldown_seconds: int = Field(default=900, alias="API_REFRESH_COOLDOWN_SECONDS")

    # Execution limits
    executor_max_items_per_run: int = Field(default=20, alias="EXECUTOR_MAX_ITEMS_PER_RUN")
    cleanup_max_delete_items: int = Field(default=20, alias="CLEANUP_MAX_DELETE_ITEMS")

    # Local UI
    local_path_presets: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="LOCAL_PATH_PRESETS")

    # Emby 媒体操作
    emby_base_url: str | None = Field(default=None, alias="EMBY_BASE_URL")
    emby_api_key: str | None = Field(default=None, alias="EMBY_API_KEY")
    emby_user_id: str | None = Field(default=None, alias="EMBY_USER_ID")
    emby_user_ids: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_USER_IDS")
    emby_media_actions_enabled: bool = Field(default=False, alias="EMBY_MEDIA_ACTIONS_ENABLED")
    emby_media_actions_strm_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_STRM_ROOTS")
    emby_media_actions_organized_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_ORGANIZED_ROOTS")
    emby_media_actions_source_roots: Annotated[list[str], NoDecode] = Field(default_factory=list, alias="EMBY_MEDIA_ACTIONS_SOURCE_ROOTS")
    emby_media_actions_delete_dry_run_default: bool = Field(default=True, alias="EMBY_MEDIA_ACTIONS_DELETE_DRY_RUN_DEFAULT")

    # External article source DB (optional)
    source_article_db_host: str | None = Field(default=None, alias="SOURCE_ARTICLE_DB_HOST")
    source_article_db_port: int = Field(default=5432, alias="SOURCE_ARTICLE_DB_PORT")
    source_article_db_name: str | None = Field(default=None, alias="SOURCE_ARTICLE_DB_NAME")
    source_article_db_user: str | None = Field(default=None, alias="SOURCE_ARTICLE_DB_USER")
    source_article_db_password: str | None = Field(default=None, alias="SOURCE_ARTICLE_DB_PASSWORD")
    source_article_search_limit: int = Field(default=20, alias="SOURCE_ARTICLE_SEARCH_LIMIT")

    # 115 cookies（供 p115client.P115Client 使用，区别于 Open API token）
    cookies_path: str = Field(default="data/cookies/cookie.txt", alias="COOKIES_PATH")

    # 115 offline download
    offline_default_target_cid: str | None = Field(default="3412729136586281899", alias="OFFLINE_DEFAULT_TARGET_CID")
    offline_submit_interval_seconds: int = Field(default=10, alias="OFFLINE_SUBMIT_INTERVAL_SECONDS")
    duplicate_check_search_limit: int = Field(default=10, alias="DUPLICATE_CHECK_SEARCH_LIMIT")

    # Single-admin auth
    auth_enabled: bool = Field(default=True, alias="AUTH_ENABLED")
    auth_username: str = Field(default="wang", alias="AUTH_USERNAME")
    auth_session_secret: str = Field(default="change-me-in-env", alias="AUTH_SESSION_SECRET")
    auth_cookie_name: str = Field(default="18x_session", alias="AUTH_COOKIE_NAME")
    auth_cookie_secure: bool = Field(default=True, alias="AUTH_COOKIE_SECURE")
    auth_cookie_samesite: str = Field(default="lax", alias="AUTH_COOKIE_SAMESITE")
    auth_session_ttl_hours: int = Field(default=24, alias="AUTH_SESSION_TTL_HOURS")
    auth_trust_proxy: bool = Field(default=True, alias="AUTH_TRUST_PROXY")
    auth_store_path: str = Field(default="data/auth.json", alias="AUTH_STORE_PATH")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator(
        "test_allowed_root_ids",
        "test_allowed_path_prefixes",
        "local_path_presets",
        "emby_user_ids",
        "emby_media_actions_strm_roots",
        "emby_media_actions_organized_roots",
        "emby_media_actions_source_roots",
        mode="before",
    )
    @classmethod
    def split_csv(cls, value: object) -> list[str]:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return [str(value).strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
