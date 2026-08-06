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
    # Pinned to 1: each worker process opens its own SQLAlchemy pool (3+2), so a
    # CPU-count default would blow the 15-client Supabase cap the moment a worker
    # is deployed. Recycle children to bound any per-process leak.
    worker_concurrency=1,
    worker_max_tasks_per_child=100,
)

# DORMANT BY DESIGN — this beat schedule is dormant by design: it never runs,
# and that is intentional.
#
# A schedule is executed only by a Celery *beat* process (`celery ... beat` or
# `celery ... worker -B`). No beat process exists anywhere: not in the Dockerfile
# (CMD is alembic+uvicorn), not in railway.json (no startCommand), not in
# infra/docker-compose.yml. A plain `celery ... worker` consumes queued tasks and
# runs no scheduler, so deploying a worker does NOT revive these entries.
#
# Beat is BANNED while the APScheduler aggregation sweep exists: enabling `-B`
# would run `aggregate_all_sites` (the unbounded full-history sweep over every
# site) concurrently with the in-process APScheduler sweep — double-scheduling
# the single most expensive query in the system.
#
#   - aggregate-visitors-hourly      -> SUPERSEDED by the APScheduler sweep in
#                                       apps/api/jobs/scheduler.py. Never revive.
#   - process-pending-visitors-hourly -> dead; likely superseded by the live
#                                       APScheduler resolution_sweep (unproven).
#   - check-segmentation-triggers     -> dead; no APScheduler equivalent.
#
# The entries are kept, not deleted, because they are the only record of the
# intended cadences. Decision owed later — see the backlog note:
# process/general-plans/active/capacity-hardening_25-07-26/celery-beat-vs-apscheduler-duplication_NOTE_25-07-26.md
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
    # Job-change detection Trigger B (staleness sweep). Daily and off-peak,
    # DELIBERATELY not on the :15 hourly cadence of process-pending-visitors:
    # both touch EnrichmentProfile, and re-checking a profile the resolution
    # pass is concurrently writing would race for no benefit. Doubly inert
    # today — the whole beat schedule is dormant (see the banner above) and
    # job_change_detection_enabled defaults False.
    "sweep-job-change-stale-profiles": {
        "task": "apps.api.tasks.job_change_tasks.sweep_stale_profiles",
        "schedule": crontab(hour=3, minute=0),
    },
}
