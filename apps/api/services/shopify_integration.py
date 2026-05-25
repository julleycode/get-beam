"""Shopify OAuth and ScriptTag integration for 1-click pixel installation."""

import hmac
import hashlib
from urllib.parse import urlencode

import httpx
import structlog

from apps.api.config import settings

logger = structlog.get_logger()

SHOPIFY_API_VERSION = "2024-01"


def get_install_url(shop_domain: str, site_id: str) -> str:
    """Generate the Shopify OAuth authorization URL."""
    # Clean domain: myshop.myshopify.com
    shop = shop_domain.strip().lower()
    if not shop.endswith(".myshopify.com"):
        # Extract shop name from various formats
        shop = shop.replace("https://", "").replace("http://", "").split("/")[0]
        if not shop.endswith(".myshopify.com"):
            shop = f"{shop}.myshopify.com"

    params = {
        "client_id": settings.shopify_api_key,
        "scope": "write_script_tags",
        "redirect_uri": f"{settings.api_base_url}/api/v1/sites/shopify/callback",
        "state": site_id,  # Pass site_id through OAuth state
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"


async def handle_oauth_callback(
    shop: str, code: str, site_id: str
) -> dict[str, str]:
    """Exchange the OAuth code for an access token and install the ScriptTag."""
    # Exchange code for token
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_response = await client.post(
            f"https://{shop}/admin/oauth/access_token",
            json={
                "client_id": settings.shopify_api_key,
                "client_secret": settings.shopify_api_secret,
                "code": code,
            },
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]

        # Install ScriptTag
        script_tag_url = (
            f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}/script_tags.json"
        )
        pixel_src = (
            f"{settings.api_base_url}/pixel/tracker.js?site={site_id}"
        )

        tag_response = await client.post(
            script_tag_url,
            json={
                "script_tag": {
                    "event": "onload",
                    "src": pixel_src,
                    "display_scope": "online_store",
                }
            },
            headers={"X-Shopify-Access-Token": access_token},
        )
        tag_response.raise_for_status()

    logger.info(
        "shopify_pixel_installed",
        shop=shop,
        site_id=site_id,
    )
    return {"status": "installed", "shop": shop, "site_id": site_id}


def verify_hmac(query_params: dict[str, str]) -> bool:
    """Verify the HMAC signature from Shopify OAuth callback."""
    hmac_value = query_params.pop("hmac", "")
    sorted_params = "&".join(
        f"{k}={v}" for k, v in sorted(query_params.items())
    )
    digest = hmac.new(
        settings.shopify_api_secret.encode(),
        sorted_params.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, hmac_value)
