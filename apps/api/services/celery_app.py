from celery import Celery
from celery.schedules import crontab

from apps.api.config import settings

# Use broker URL if set, otherwise use in-memory transport (no-op for web-only deploy)
broker_url = settings.celery_broker_url or "memory://"
backend_url = settings.celery_result_backend or "cache+memory://"

celery_app = Celery(
    "retarget_agent",
    broker=broker_url,
    backend=backend_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "aggregate-visitors-hourly": {
        "task": "apps.api.tasks.aggregation_tasks.aggregate_all_sites",
        "schedule": crontab(minute="0"),
    },
    "process-pending-visitors-hourly": {
        "task": "apps.api.tasks.resolution_tasks.process_all_pending_visitors",
        "schedule": crontab(minute="15"),
    },
    "check-segmentation-triggers": {
        "task": "apps.api.tasks.segmentation_tasks.check_segmentation_triggers",
        "schedule": crontab(minute="30"),
    },
}
