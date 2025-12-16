# Create this file: yourapp/services.py

import requests
import socket
import json
import time
from django.core.cache import cache
from django.conf import settings
import logging
from ..models import Layer
# core/views.py
from core.services.layer_features import fetch_layer_features_with_attributes


logger = logging.getLogger(__name__)


class ServiceHealthManager:
    """
    Manages ArcGIS service health and caches failed services to avoid repeated requests
    """

    CACHE_PREFIX = 'service_health_'
    FAILURE_CACHE_TIME = 300  # 5 minutes
    SUCCESS_CACHE_TIME = 60  # 1 minute

    @classmethod
    def is_service_healthy(cls, server_url, layer_number=None):
        """
        Check if a service is healthy (cached for performance)

        Args:
            server_url: Base server URL
            layer_number: Optional layer number for specific layer check

        Returns:
            bool: True if service is healthy, False otherwise
        """
        cache_key = f"{cls.CACHE_PREFIX}{server_url}"
        if layer_number:
            cache_key += f"_{layer_number}"

        # Check cache first
        cached_result = cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Test the service
        is_healthy = cls._test_service(server_url, layer_number)

        # Cache the result
        cache_time = cls.SUCCESS_CACHE_TIME if is_healthy else cls.FAILURE_CACHE_TIME
        cache.set(cache_key, is_healthy, cache_time)

        return is_healthy

    @classmethod
    def _test_service(cls, server_url, layer_number=None):
        """
        Actually test the service connectivity
        """
        try:
            # First test DNS resolution
            from urllib.parse import urlparse
            parsed_url = urlparse(server_url)
            if parsed_url.hostname:
                socket.gethostbyname(parsed_url.hostname)
            else:
                return False

            # Test basic server connectivity
            test_url = server_url.rstrip('/')
            if layer_number is not None:
                test_url += f"/{layer_number}"

            response = requests.get(
                f"{test_url}?f=json",
                timeout=5,
                headers={'User-Agent': 'GIS-App/1.0'}
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                    # Check if it's a valid ArcGIS response
                    if 'error' in data:
                        logger.warning(f"ArcGIS service error for {test_url}: {data['error']}")
                        return False
                    return True
                except json.JSONDecodeError:
                    return False
            else:
                logger.warning(f"HTTP {response.status_code} for {test_url}")
                return False

        except socket.gaierror:
            logger.error(f"DNS resolution failed for {server_url}")
            return False
        except requests.exceptions.Timeout:
            logger.warning(f"Timeout connecting to {server_url}")
            return False
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error to {server_url}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error testing {server_url}: {e}")
            return False

    @classmethod
    def mark_service_failed(cls, server_url, layer_number=None):
        """Mark a service as failed for faster future checks"""
        cache_key = f"{cls.CACHE_PREFIX}{server_url}"
        if layer_number:
            cache_key += f"_{layer_number}"

        cache.set(cache_key, False, cls.FAILURE_CACHE_TIME)
        logger.info(f"Marked service as failed: {cache_key}")

    @classmethod
    def clear_service_cache(cls, server_url=None):
        """Clear service health cache"""
        if server_url:
            cache_key = f"{cls.CACHE_PREFIX}{server_url}"
            cache.delete(cache_key)
        else:
            # Clear all service health cache
            # This is database-dependent, implement as needed
            pass

    @classmethod
    def get_service_status_summary(cls):
        """Get a summary of all service statuses"""

        servers = {}
        layers = Layer.objects.select_related('server').filter(server__isnull=False)

        for layer in layers:
            server_url = layer.server.url
            if server_url not in servers:
                servers[server_url] = {
                    'name': layer.server.name,
                    'url': server_url,
                    'healthy': cls.is_service_healthy(server_url),
                    'layer_count': 0,
                    'healthy_layers': 0
                }

            servers[server_url]['layer_count'] += 1

            # Check individual layer health
            if cls.is_service_healthy(server_url, layer.number):
                servers[server_url]['healthy_layers'] += 1

        return servers


class RobustArcGISClient:
    """
    A robust client for ArcGIS services with retry logic and error handling
    """

    def __init__(self, max_retries=2, timeout=10):
        self.max_retries = max_retries
        self.timeout = timeout

    def query_features(self, layer, minx, miny, maxx, maxy, limit=2000, out_sr=4326):
        """
        Query features from a layer with robust error handling
        """
        if not layer.server:
            logger.warning(f"Layer {layer.name} has no server configured")
            return []

        # Check service health first
        if not ServiceHealthManager.is_service_healthy(layer.server.url, layer.number):
            logger.info(f"Skipping unhealthy service: {layer.server.url}/{layer.number}")
            return []

        # Handle offset points (local data)
        if (layer.type == 'point' and
                layer.offsetX is not None and layer.offsetY is not None and
                layer.offsetX != 0 and layer.offsetY != 0):

            if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
                try:
                    from django.contrib.gis.geos import Point
                    point = Point(layer.offsetX, layer.offsetY, srid=4326)
                    return [point]
                except Exception as e:
                    logger.error(f"Error creating offset point: {e}")

        # Build query URL
        base_url = layer.server.url.rstrip('/')
        url = f"{base_url}/{layer.number}/query"

        params = {
            'f': 'geojson',
            'where': '1=1',
            'geometry': f"{minx},{miny},{maxx},{maxy}",
            'geometryType': 'esriGeometryEnvelope',
            'spatialRel': 'esriSpatialRelIntersects',
            'inSR': 4326,
            'outSR': out_sr,
            'returnGeometry': 'true',
            'outFields': '*',
            'maxRecordCount': limit
        }

        # Retry logic
        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(f"Querying {layer.name} (attempt {attempt + 1}/{self.max_retries + 1})")

                response = requests.get(
                    url,
                    params=params,
                    timeout=self.timeout,
                    headers={'User-Agent': 'GIS-App/1.0'}
                )

                response.raise_for_status()

                # Check content type
                content_type = response.headers.get('content-type', '').lower()
                if 'html' in content_type:
                    raise ValueError("Received HTML response instead of JSON")

                try:
                    data = response.json()
                except json.JSONDecodeError as e:
                    raise ValueError(f"Invalid JSON response: {e}")

                # Check for ArcGIS errors
                if 'error' in data:
                    error_msg = data['error'].get('message', 'Unknown ArcGIS error')
                    raise ValueError(f"ArcGIS error: {error_msg}")

                # Process features
                features = data.get('features', [])
                geometries = []

                for feature in features[:limit]:
                    geom_data = feature.get('geometry')
                    if geom_data:
                        try:
                            from django.contrib.gis.geos import GEOSGeometry
                            geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
                            if geom.valid:
                                geometries.append(geom)
                        except Exception as e:
                            logger.debug(f"Error processing geometry: {e}")
                            continue

                logger.debug(f"Successfully fetched {len(geometries)} features for {layer.name}")
                return geometries

            except requests.exceptions.Timeout:
                logger.warning(f"Timeout querying {layer.name} (attempt {attempt + 1})")
                if attempt == self.max_retries:
                    ServiceHealthManager.mark_service_failed(layer.server.url, layer.number)
                    return []
                time.sleep(1)  # Brief pause before retry

            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Connection error querying {layer.name}: {e}")
                ServiceHealthManager.mark_service_failed(layer.server.url, layer.number)
                return []

            except ValueError as e:
                logger.error(f"Data error querying {layer.name}: {e}")
                if attempt == self.max_retries:
                    ServiceHealthManager.mark_service_failed(layer.server.url, layer.number)
                return []

            except Exception as e:
                logger.error(f"Unexpected error querying {layer.name}: {e}")
                if attempt == self.max_retries:
                    ServiceHealthManager.mark_service_failed(layer.server.url, layer.number)
                return []

        return []

    def query_features_with_attributes(self, layer, minx, miny, maxx, maxy, limit=2000, out_sr=28356):
        """
        Query features with full attributes
        """
        # Similar to query_features but returns dict with geometry and attributes
        # Implementation similar to the above but preserving attributes
        if not ServiceHealthManager.is_service_healthy(layer.server.url, layer.number):
            return []

        # ... (implement similar to fetch_layer_features_with_attributes but with robust error handling)
        # For brevity, using the existing function structure
        
        return fetch_layer_features_with_attributes(layer, minx, miny, maxx, maxy, limit, out_sr)


# Utility functions for management commands and debugging

def test_all_services():
    """Test all services and return results"""

    results = {}
    layers = Layer.objects.select_related('server').filter(server__isnull=False)

    for layer in layers:
        server_key = f"{layer.server.name}_{layer.server.url}"
        if server_key not in results:
            results[server_key] = {
                'server': layer.server,
                'layers': [],
                'healthy': ServiceHealthManager.is_service_healthy(layer.server.url)
            }

        layer_healthy = ServiceHealthManager.is_service_healthy(layer.server.url, layer.number)
        results[server_key]['layers'].append({
            'layer': layer,
            'healthy': layer_healthy
        })

    return results


def clear_all_service_cache():
    """Clear all service health cache"""
    from django.core.cache import cache

    # Get all cache keys with our prefix
    # This is a simplified version - in production you might want to use cache.delete_pattern
    ServiceHealthManager.clear_service_cache()


def get_failing_services():
    """Get list of currently failing services"""
    results = test_all_services()
    failing = []

    for server_key, info in results.items():
        if not info['healthy']:
            failing.append({
                'server': info['server'],
                'layers': [l['layer'] for l in info['layers']]
            })

    return failing