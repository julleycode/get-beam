import clickhouse_connect
from apps.api.config import get_settings

settings = get_settings()

_client = None


def get_client():
    global _client
    if _client is None:
        _client = clickhouse_connect.get_client(
            host=settings.clickhouse_host,
            port=settings.clickhouse_port,
            database=settings.clickhouse_db,
            username=settings.clickhouse_user,
            password=settings.clickhouse_password,
        )
    return _client


CREATE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS retarget.events (
    event_id     String,
    pixel_id     String,
    anonymous_id String,
    event_type   String,
    page_url     String,
    page_title   String,
    referrer     String,
    scroll_depth Float32,
    time_on_page UInt32,
    properties   String,
    ip           String,
    user_agent   String,
    timestamp    DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (pixel_id, anonymous_id, timestamp)
PARTITION BY toYYYYMM(timestamp)
TTL timestamp + INTERVAL 1 YEAR
"""


def init_clickhouse():
    client = get_client()
    client.command("CREATE DATABASE IF NOT EXISTS retarget")
    client.command(CREATE_EVENTS_TABLE)
    print("ClickHouse schema initialized.")


def insert_event(event: dict):
    client = get_client()
    client.insert(
        "retarget.events",
        [[
            event.get("event_id", ""),
            event.get("pixel_id", ""),
            event.get("anonymous_id", ""),
            event.get("event_type", ""),
            event.get("page_url", ""),
            event.get("page_title", ""),
            event.get("referrer", ""),
            float(event.get("scroll_depth", 0)),
            int(event.get("time_on_page", 0)),
            str(event.get("properties", "{}")),
            event.get("ip", ""),
            event.get("user_agent", ""),
        ]],
        column_names=[
            "event_id", "pixel_id", "anonymous_id", "event_type",
            "page_url", "page_title", "referrer", "scroll_depth",
            "time_on_page", "properties", "ip", "user_agent"
        ]
    )


def get_visitor_stats(pixel_id: str, anonymous_id: str) -> dict:
    client = get_client()
    result = client.query("""
        SELECT
            count() as page_views,
            sum(time_on_page) as total_time,
            max(timestamp) as last_seen,
            groupArray(page_url) as pages
        FROM retarget.events
        WHERE pixel_id = {pixel_id:String}
          AND anonymous_id = {anon_id:String}
          AND event_type = 'pageview'
    """, parameters={"pixel_id": pixel_id, "anon_id": anonymous_id})
    if result.result_rows:
        row = result.result_rows[0]
        pages = list(set(row[3]))[:10]
        return {
            "page_views": row[0],
            "total_time_seconds": row[1],
            "last_seen": str(row[2]),
            "top_pages": pages,
        }
    return {"page_views": 0, "total_time_seconds": 0, "top_pages": []}
