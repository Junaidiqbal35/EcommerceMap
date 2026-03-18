"""
Celery tasks for GIS Layer maintenance.

Daily task to:
- Validate layer coordinates are within Australia
- Fix invalid coordinates automatically
- Clean up old download records
"""

import logging
from datetime import timedelta
from celery import shared_task
from django.contrib.gis.geos import Point
from django.utils import timezone

from core.gda2020_converter import GDA2020Converter

logger = logging.getLogger(__name__)

# Initialize converter
gda_converter = GDA2020Converter()

# Server-specific coordinate fixes for known problematic servers
SERVER_COORDINATES = {
    # Perth
    30: (115.849, -31.966), 31: (115.848, -31.966), 13: (115.862, -31.955),
    # Sydney
    27: (151.204, -33.889), 28: (151.204, -33.889), 29: (151.204, -33.889),
    # Queensland
    1: (145.752, -18.999), 4: (152.902, -26.708), 5: (149.789, -22.930),
    6: (153.373, -27.944), 7: (153.368, -27.943), 8: (153.360, -27.967),
    # SEQ Water
    2: (152.963, -26.846), 3: (152.629, -26.653),
    9: (152.900, -26.800), 10: (152.900, -26.800),
    # Other
    11: (153.044, -27.413), 12: (149.807, -32.875), 14: (153.336, -27.524),
    15: (147.000, -42.000), 16: (146.800, -19.400), 17: (151.388, -27.519),
    19: (121.000, -24.000), 25: (145.772, -19.580), 26: (152.851, -26.708),
}


@shared_task
def daily_layer_maintenance():
    """
    Daily maintenance task that runs at 2 AM.

    1. Validates all layer coordinates
    2. Fixes invalid coordinates
    3. Cleans up download records older than 90 days
    """
    from core.models import Layer, DownloadRecord

    logger.info("Starting daily layer maintenance...")

    results = {
        'layers_checked': 0,
        'layers_fixed': 0,
        'downloads_cleaned': 0
    }

    # 1. Validate and fix layer coordinates
    for layer in Layer.objects.select_related('server').all():
        results['layers_checked'] += 1

        if layer.offsetX is None or layer.offsetY is None:
            continue

        # Check if coordinates are valid using GDA2020Converter
        if not gda_converter.is_in_australia(layer.offsetY, layer.offsetX):
            fixed = fix_layer(layer)
            if fixed:
                results['layers_fixed'] += 1

    # 2. Clean up old download records (older than 90 days)
    cutoff = timezone.now() - timedelta(days=90)
    deleted, _ = DownloadRecord.objects.filter(downloaded_at__lt=cutoff).delete()
    results['downloads_cleaned'] = deleted

    logger.info(
        f"Maintenance complete: {results['layers_checked']} checked, "
        f"{results['layers_fixed']} fixed, {results['downloads_cleaned']} cleaned"
    )

    return results


def fix_layer(layer) -> bool:
    """Fix a layer's invalid coordinates."""
    # Try server center first
    server = layer.server
    if server and all([server.extent_min_x, server.extent_min_y,
                       server.extent_max_x, server.extent_max_y]):
        center_x = (server.extent_min_x + server.extent_max_x) / 2
        center_y = (server.extent_min_y + server.extent_max_y) / 2

        if gda_converter.is_in_australia(center_y, center_x):
            layer.offsetX = center_x
            layer.offsetY = center_y
            layer.geometry = Point(center_x, center_y, srid=4326)
            layer.save()

            # Log zone info
            zone_info = gda_converter.get_zone_info(center_y, center_x)
            if zone_info:
                logger.info(f"Fixed layer {layer.layer_id}: Zone {zone_info['utm_zone']}")
            return True

    # Try known server coordinates
    if layer.server_id in SERVER_COORDINATES:
        coords = SERVER_COORDINATES[layer.server_id]
        layer.offsetX, layer.offsetY = coords
        layer.geometry = Point(coords[0], coords[1], srid=4326)
        layer.save()
        return True

    return False