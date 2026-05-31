"""Generate a WordPress plugin .zip file with pre-configured site ID."""

import io
import zipfile

import structlog

logger = structlog.get_logger()

PLUGIN_TEMPLATE = """<?php
/**
 * Plugin Name: Beam Tracking Pixel
 * Description: Automatically adds the Beam visitor tracking pixel to your website.
 * Version: 1.0.0
 * Author: Beam (getbeam.fyi)
 * License: MIT
 */

if (!defined('ABSPATH')) exit;

function beam_add_pixel() {{
    echo '<script src="{api_url}/pixel/tracker.js" data-site="{site_id}" data-api="{api_url}" defer></script>' . "\\n";
}}

add_action('wp_head', 'beam_add_pixel', 1);
"""

README_TEMPLATE = """=== Beam Tracking Pixel ===

This plugin adds the Beam tracking pixel to your WordPress site.

== Installation ==

1. Upload this plugin to your WordPress site (Plugins > Add New > Upload Plugin)
2. Click "Activate"
3. That's it! The pixel is now tracking visitors.

== Configuration ==

This plugin is pre-configured for your site:
- Site ID: {site_id}
- API URL: {api_url}

No additional configuration needed.

Learn more at https://getbeam.fyi
"""


def generate_plugin_zip(site_id: str, api_url: str) -> bytes:
    """Generate a WordPress plugin .zip file with the site_id and api_url baked in."""
    plugin_code = PLUGIN_TEMPLATE.format(site_id=site_id, api_url=api_url)
    readme = README_TEMPLATE.format(site_id=site_id, api_url=api_url)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "beam-pixel/beam-pixel.php",
            plugin_code,
        )
        zf.writestr(
            "beam-pixel/readme.txt",
            readme,
        )

    logger.info("wordpress_plugin_generated", site_id=site_id)
    return buffer.getvalue()
