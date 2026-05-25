from clickhouse_connect.driver.client import Client
import clickhouse_connect
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

_client = None
_unavailable = False


def get_clickhouse_client() -> Client | None:
    global _client, _unavailable
    if _unavailable:
        return None
    if _client is None:
        try:
            _client = clickhouse_connect.get_client(
                host=settings.clickhouse_host,
                port=settings.clickhouse_port,
                username=settings.clickhouse_user,
                password=settings.clickhouse_password,
                database=settings.clickhouse_db,
            )
        except Exception as e:
            logger.warning("clickhouse_unavailable", error=str(e))
            _unavailable = True
            return None
    return _client


def init_clickhouse_schema() -> None:
    client = get_clickhouse_client()
    if client is None:
        logger.warning("clickhouse_unavailable_skipping_schema_init")
        return
    client.command("""
        CREATE TABLE IF NOT EXISTS events (
            site_id String,
            visitor_id String,
            event_type String,
            url String DEFAULT '',
            referrer String DEFAULT '',
            utm_source String DEFAULT '',
            utm_medium String DEFAULT '',
            utm_campaign String DEFAULT '',
            country_code String DEFAULT '',
            region String DEFAULT '',
            device_type String DEFAULT '',
            browser_lang String DEFAULT '',
            scroll_depth UInt8 DEFAULT 0,
            time_on_page UInt32 DEFAULT 0,
            element_text String DEFAULT '',
            element_href String DEFAULT '',
            ip_address String DEFAULT '',
            created_at DateTime DEFAULT now()
        ) ENGINE = MergeTree()
        ORDER BY (site_id, visitor_id, created_at)
        TTL created_at + INTERVAL 90 DAY
    """)
    logger.info("clickhouse_schema_initialized")
