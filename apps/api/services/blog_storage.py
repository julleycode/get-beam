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

    # Remove ALL whitespace — a pasted env var can carry a newline (even in the
    # middle, from a wrapped paste box), which is an illegal HTTP header value
    # (h11 LocalProtocolError). .strip() only handles the ends; keys/urls never
    # contain internal whitespace, so collapsing it all is safe.
    key = "".join(settings.supabase_service_role_key.split())
    base = "".join(settings.supabase_url.split()).rstrip("/")
    url = f"{base}/storage/v1/object/{settings.supabase_storage_bucket}/{path}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                url,
                content=data,
                headers={
                    # Supabase's gateway needs BOTH headers. The new `sb_secret_`
                    # keys are rejected with Authorization alone — `apikey` routes
                    # + authorizes the request.
                    "apikey": key,
                    "Authorization": f"Bearer {key}",
                    "Content-Type": content_type,
                    "x-upsert": "true",
                },
            )
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:160].replace("\n", " ")
        logger.warning(
            "blog_image_upload_failed",
            status=exc.response.status_code,
            body=exc.response.text[:300],
        )
        raise UploadError(f"Supabase {exc.response.status_code}: {detail}") from exc
    except httpx.HTTPError as exc:
        logger.warning("blog_image_upload_failed", error=str(exc))
        raise UploadError(f"Cannot reach Supabase ({type(exc).__name__})") from exc

    logger.info("blog_image_uploaded", path=path)
    return public_url(path)
