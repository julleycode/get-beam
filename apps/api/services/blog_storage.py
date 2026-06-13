"""Upload blog images to Supabase Storage (bucket `blog-images`).

Mock mode: when no service-role key is configured (local dev / tests), returns
a deterministic fake public URL instead of calling Supabase — mirrors the
key-absence mock pattern used by the enrichment services.
"""

import uuid

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

# content-type → file extension. Mirrors the bucket's allowed_mime_types.
_ALLOWED: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/svg+xml": "svg",
}
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB — matches the bucket file_size_limit.


class UploadError(Exception):
    """Raised for invalid uploads or a failed Supabase call."""


def _extension(content_type: str) -> str:
    ext = _ALLOWED.get(content_type)
    if ext is None:
        raise UploadError(f"Unsupported image type: {content_type or 'unknown'}")
    return ext


def public_url(path: str) -> str:
    base = (settings.supabase_url or "https://mock.supabase.co").rstrip("/")
    return f"{base}/storage/v1/object/public/{settings.supabase_storage_bucket}/{path}"


async def upload_image(data: bytes, content_type: str) -> str:
    """Upload image bytes, return the public URL. Raises UploadError on bad input/failure."""
    ext = _extension(content_type)
    if not data:
        raise UploadError("Empty file")
    if len(data) > _MAX_BYTES:
        raise UploadError("Image exceeds the 5MB limit")

    path = f"{uuid.uuid4().hex}.{ext}"

    # Mock fallback — no credentials configured.
    if not settings.supabase_service_role_key or not settings.supabase_url:
        logger.info("blog_image_mock_upload", path=path)
        return public_url(path)

    base = settings.supabase_url.rstrip("/")
    url = f"{base}/storage/v1/object/{settings.supabase_storage_bucket}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                content=data,
                headers={
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
            )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("blog_image_upload_failed", error=str(exc))
        raise UploadError("Image upload failed") from exc

    logger.info("blog_image_uploaded", path=path)
    return public_url(path)
