from collections import defaultdict

from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET, require_POST

from django.template.response import TemplateResponse

from django.db.models import Q
from typing import List, Dict, Any, Optional

from requests.adapters import HTTPAdapter
from urllib3 import Retry
from django.core.cache import cache
from .models import Layer, DownloadRecord, UserLayerPreference
from .gda2020_converter import GDA2020Converter

from django.contrib.gis.geos import (
    GEOSGeometry, Point, LineString, Polygon,
    MultiPoint, MultiLineString, MultiPolygon
)
import json
import requests
import ezdxf
from ezdxf import colors
import math
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Constants
MAX_DOWNLOAD_AREA = 0.005
CACHE_TIMEOUT = 300
# Reasonable limit for CAD performance
MAX_FEATURES_PER_LAYER = 5000
TEXT_HEIGHT = 0.4
TEXT_OFFSET = 1.2
TEXT_OFFSET_X = 1.2
TEXT_OFFSET_Y = 1.2
DECIMAL = 3


@login_required
@require_GET
def all_layers(request):
    """
    Return all layers with basic information as JSON.
    Includes user's preferred layers for highlighting.
    """
    layers = Layer.objects.select_related('server').filter(
        server__isnull=False
    ).order_by('server__name', 'name')

    # Get user's preferred layer IDs
    preferred_layer_ids = UserLayerPreference.get_preferred_layer_ids(request.user)

    data = []
    for layer in layers:
        # Get centroid if geometry exists
        centroid_lat = centroid_lng = None
        if layer.geometry:
            try:
                centroid = layer.geometry.centroid
                # Ensure coordinates are within valid range
                if -90 <= centroid.y <= 90 and -180 <= centroid.x <= 180:
                    centroid_lat = centroid.y
                    centroid_lng = centroid.x
            except:
                pass

        data.append({
            'id': layer.layer_id,
            'name': layer.name,
            'type': layer.type,
            'server_name': layer.server.name if layer.server else 'Unknown',
            'centroid_lat': centroid_lat,
            'centroid_lng': centroid_lng,
            'is_preferred': layer.layer_id in preferred_layer_ids,  # NEW
        })

    return JsonResponse({
        'layers': data,
        'preferred_layer_ids': preferred_layer_ids,  # NEW
    })

def create_session_with_retries(max_retries=3):
    """Create a requests session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def parse_esri_geometry(geom_dict: Dict, srid: int = 4326) -> Optional[GEOSGeometry]:
    """
    Convert ESRI JSON geometry to GEOS geometry.
    Handles all ESRI geometry types.
    """
    if not geom_dict:
        return None

    try:
        # Point geometry
        if 'x' in geom_dict and 'y' in geom_dict:
            x = float(geom_dict['x'])
            y = float(geom_dict['y'])
            # Handle invalid coordinates
            if abs(x) > 180 or abs(y) > 90:
                # Might be in different projection, try anyway
                pass
            return Point(x, y, srid=srid)

        # MultiPoint
        elif 'points' in geom_dict:
            points = []
            for p in geom_dict['points']:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    points.append(Point(p[0], p[1], srid=srid))
            if points:
                return MultiPoint(points, srid=srid)

        # Polyline/LineString
        elif 'paths' in geom_dict:
            paths = geom_dict['paths']
            if not paths:
                return None

            lines = []
            for path in paths:
                if len(path) >= 2:
                    try:
                        line = LineString(path, srid=srid)
                        if line.valid:
                            lines.append(line)
                    except:
                        continue

            if len(lines) == 1:
                return lines[0]
            elif len(lines) > 1:
                return MultiLineString(lines, srid=srid)

        # Polygon
        elif 'rings' in geom_dict:
            rings = geom_dict['rings']
            if not rings:
                return None

            # Filter out invalid rings
            valid_rings = []
            for ring in rings:
                if len(ring) >= 3:  # Minimum for a valid ring
                    valid_rings.append(ring)

            if not valid_rings:
                return None

            try:
                # First ring is exterior, rest are holes
                if len(valid_rings) == 1:
                    poly = Polygon(valid_rings[0], srid=srid)
                else:
                    poly = Polygon(valid_rings[0], *valid_rings[1:], srid=srid)

                if poly.valid:
                    return poly
                else:
                    # Try to fix invalid polygon
                    poly = poly.buffer(0)
                    return poly
            except:
                # Try creating without holes
                try:
                    return Polygon(valid_rings[0], srid=srid)
                except:
                    return None

        # GeoJSON format (some servers return this even with f=json)
        elif 'type' in geom_dict and 'coordinates' in geom_dict:
            try:
                geom = GEOSGeometry(json.dumps(geom_dict), srid=srid)
                if geom.valid:
                    return geom
            except:
                pass

    except Exception as e:
        logger.debug(f"Error parsing ESRI geometry: {e}")

    return None


@login_required
def home(request):
    """
    Main map page - FIXED to pass preferred_layer_ids to template.
    This enables auto-selection of user's preferred layers on page load.
    """
    # Get user's preferred layer IDs
    preferred_layer_ids = UserLayerPreference.get_preferred_layer_ids(request.user)

    return render(request, "home.html", {
        'preferred_layer_ids': json.dumps(preferred_layer_ids),
    })


@login_required
@require_GET
def user_connects(request):
    """Return user connects for display"""
    connects = getattr(request.user, 'connects', 0)
    return TemplateResponse(request, 'partials/user_connects.html', {
        'connects': connects
    })


@login_required
@require_GET
def layer_list(request):
    """
    Return filtered layer list with user preferences.
    Supports search, type filter, and 'preferred' filter.
    """
    search = request.GET.get('search', '').strip()
    filter_type = request.GET.get('filter', 'all').lower()

    # Get user's preferred layer IDs
    preferred_layer_ids = UserLayerPreference.get_preferred_layer_ids(request.user)

    # Start with all layers
    layers = Layer.objects.select_related('server').all()

    # Apply search filter
    if search:
        layers = layers.filter(name__icontains=search)

    # Apply type/category filters
    if filter_type == 'preferred':
        # Show only preferred layers
        if preferred_layer_ids:
            layers = layers.filter(layer_id__in=preferred_layer_ids)
        else:
            layers = layers.none()
    elif filter_type == 'water':
        layers = layers.filter(name__icontains='WAT') | layers.filter(name__icontains='SEW')
    elif filter_type == 'electric':
        layers = layers.filter(name__icontains='ELEC')
    elif filter_type == 'road':
        layers = layers.filter(name__icontains='ROAD') | layers.filter(name__icontains='STREET')
    elif filter_type == 'contour':
        layers = layers.filter(name__icontains='CONTOUR')

    # Group by server
    grouped_layers = defaultdict(list)
    for layer in layers:
        server_name = layer.server.name if layer.server else 'Unknown'
        grouped_layers[server_name].append(layer)

    # Sort servers alphabetically
    grouped_layers = dict(sorted(grouped_layers.items()))

    return TemplateResponse(request, 'partials/layer_list.html', {
        'grouped_layers': grouped_layers,
        'preferred_layer_ids': preferred_layer_ids,
        'filter_type': filter_type,
        'search': search,
        'total_count': layers.count(),
    })


# ==============================================================================
# 3. REPLACE the log_export_records() function (around line 1310) with this:
# ==============================================================================

def log_export_records(user, layers, lat, lng):
    """Log download records and update user layer preferences"""

    records = []
    for layer in layers:
        records.append(DownloadRecord(
            user=user,
            layer=layer,
            latitude=lat,
            longitude=lng
        ))

    # Bulk create download records for efficiency
    DownloadRecord.objects.bulk_create(records, ignore_conflicts=True)

    # Update user layer preferences (track frequently downloaded layers)
    for layer in layers:
        UserLayerPreference.update_preference(user, layer)


# ==============================================================================
# 4. ADD these new view functions (optional - for managing preferences)
# ==============================================================================

@login_required
@require_GET
def user_layer_preferences(request):
    """
    API endpoint to get user's preferred layer IDs.
    Used by JavaScript to initialize preferred layers on page load.
    """
    preferred_ids = UserLayerPreference.get_preferred_layer_ids(request.user)

    # Optionally include layer details
    include_details = request.GET.get('details', 'false').lower() == 'true'

    if include_details:
        preferences = UserLayerPreference.objects.filter(
            user=request.user
        ).select_related('layer', 'layer__server').order_by('-download_count')[:50]

        return JsonResponse({
            'success': True,
            'preferred_ids': preferred_ids,
            'preferences': [
                {
                    'layer_id': p.layer_id,
                    'layer_name': p.layer.name,
                    'server_name': p.layer.server.name if p.layer.server else 'Unknown',
                    'download_count': p.download_count,
                    'is_favorite': p.is_favorite,
                    'last_used': p.last_used.isoformat(),
                }
                for p in preferences
            ]
        })

    return JsonResponse({
        'success': True,
        'preferred_ids': preferred_ids,
    })


@login_required
@require_POST
def clear_layer_preferences(request):
    """Clear all layer preferences for the current user."""
    deleted_count, _ = UserLayerPreference.objects.filter(user=request.user).delete()

    return JsonResponse({
        'success': True,
        'message': f'Cleared {deleted_count} layer preferences',
        'deleted_count': deleted_count,
    })


@login_required
@require_POST
def toggle_layer_favorite(request, layer_id):
    """Toggle favorite status for a specific layer."""
    is_favorite = UserLayerPreference.toggle_favorite(request.user, layer_id)

    return JsonResponse({
        'success': True,
        'layer_id': layer_id,
        'is_favorite': is_favorite,
    })


def log_export_records(user, layers, lat=None, lng=None):
    """
    Log download records and update user preferences.
    Called by export_dxf_multi after successful export.
    """
    for layer in layers:
        # Create download record
        DownloadRecord.objects.create(
            user=user,
            layer=layer,
            latitude=lat,
            longitude=lng
        )

        # Update user preference (increment download count)
        UserLayerPreference.update_preference(user, layer)

    logger.info(f"Logged {len(layers)} downloads for user {user.username}")

@login_required
def layer_preview_features(request):
    """
    Robust layer preview with maximum compatibility.
    Always returns valid JSON for better frontend handling.
    """
    # Get parameters
    layer_id = request.GET.get('layer_id')
    minx = request.GET.get('minx')
    miny = request.GET.get('miny')
    maxx = request.GET.get('maxx')
    maxy = request.GET.get('maxy')

    # Create base response structure
    response_data = {
        'type': 'FeatureCollection',
        'features': [],
        'metadata': {
            'layer_id': layer_id,
            'feature_count': 0
        }
    }

    # Validate parameters
    if not all([layer_id, minx, miny, maxx, maxy]):
        response_data['message'] = 'Missing parameters'
        response_data['error'] = True
        return JsonResponse(response_data)

    try:
        layer = Layer.objects.select_related('server').get(layer_id=layer_id)
        response_data['metadata']['layer_name'] = layer.name
        response_data['metadata']['layer_type'] = layer.type
        response_data['metadata']['server'] = layer.server.name if layer.server else 'Unknown'
    except Layer.DoesNotExist:
        response_data['message'] = 'Layer not found'
        response_data['error'] = True
        return JsonResponse(response_data)

    try:
        # Parse coordinates
        minx, miny = float(minx), float(miny)
        maxx, maxy = float(maxx), float(maxy)

        # Validate coordinate ranges
        if not (-180 <= minx <= 180 and -180 <= maxx <= 180 and
                -90 <= miny <= 90 and -90 <= maxy <= 90):
            response_data['message'] = 'Invalid coordinates'
            response_data['error'] = True
            return JsonResponse(response_data)

    except (ValueError, TypeError):
        response_data['message'] = 'Invalid coordinate format'
        response_data['error'] = True
        return JsonResponse(response_data)

    # Calculate area and zoom level
    width = maxx - minx
    height = maxy - miny
    area = width * height

    # Estimate zoom level
    if area < 0.00001:
        zoom_level = 18
    elif area < 0.0001:
        zoom_level = 16
    elif area < 0.001:
        zoom_level = 14
    elif area < 0.01:
        zoom_level = 12
    elif area < 0.1:
        zoom_level = 10
    else:
        zoom_level = 8

    response_data['metadata']['zoom_level'] = zoom_level
    response_data['metadata']['bounds'] = {
        'minx': minx, 'miny': miny,
        'maxx': maxx, 'maxy': maxy
    }

    # Adjust feature limit based on zoom
    feature_limit = 1000 if zoom_level >= 16 else 500 if zoom_level >= 14 else 200 if zoom_level >= 12 else 100

    # Check if area is too large
    if area > 0.5:  # About 50km x 50km
        response_data['message'] = f'Zoom in to see features (current zoom: ~{zoom_level})'
        response_data['hint'] = 'Area too large for preview'
        return JsonResponse(response_data)

    # Check if server is configured
    if not layer.server:
        response_data['message'] = 'Server not configured'
        response_data['error'] = True
        return JsonResponse(response_data)

    # Try to fetch features
    try:
        features_data = fetch_layer_features_with_attributes(
            layer, minx, miny, maxx, maxy,
            limit=feature_limit,
            out_sr=4326,  # Always use WGS84 for web display
            preview_mode=True
        )
    except Exception as e:
        logger.error(f"Error fetching features for {layer.name}: {e}")
        features_data = []

    # If no features and zoom is high, try expanding area
    if not features_data and zoom_level >= 14:
        buffer = 0.001  # About 100m
        try:
            features_data = fetch_layer_features_with_attributes(
                layer,
                minx - buffer, miny - buffer,
                maxx + buffer, maxy + buffer,
                limit=feature_limit,
                out_sr=4326,
                preview_mode=True
            )
        except:
            pass

    # Convert to GeoJSON features
    geojson_features = []

    for feature_info in features_data:
        if len(geojson_features) >= feature_limit:
            break

        geom = feature_info.get('geometry')
        attrs = feature_info.get('attributes', {})

        if not geom or not geom.valid:
            continue

        try:
            # Ensure geometry is in WGS84
            if geom.srid != 4326:
                try:
                    geom.transform(4326)
                except:
                    continue

            # Simplify geometry if needed
            if zoom_level <= 12 and geom.geom_type in ['Polygon', 'MultiPolygon']:
                try:
                    tolerance = 0.0001 * (15 - zoom_level)
                    geom = geom.simplify(tolerance, preserve_topology=True)
                except:
                    pass

            # Build properties
            preview_attrs = {
                'layer_name': layer.name,
                'layer_type': layer.type,
                'layer_id': layer.layer_id,
            }

            # Add important attributes
            important_keys = [
                'objectid', 'OBJECTID', 'id', 'ID',
                'name', 'NAME', 'type', 'TYPE',
                'status', 'STATUS', 'material', 'MATERIAL',
                'diameter', 'DIAMETER', 'width', 'WIDTH'
            ]

            for key in important_keys:
                if key in attrs and attrs[key] is not None:
                    preview_attrs[key.lower()] = str(attrs[key])[:100]

            # Create GeoJSON feature
            feature = {
                'type': 'Feature',
                'geometry': json.loads(geom.geojson),
                'properties': preview_attrs
            }

            geojson_features.append(feature)

        except Exception as e:
            logger.debug(f"Error creating GeoJSON feature: {e}")
            continue

    # Update response
    response_data['features'] = geojson_features
    response_data['metadata']['feature_count'] = len(geojson_features)

    # Add appropriate message
    if not geojson_features:
        if zoom_level < 12:
            response_data['message'] = 'Zoom in to see features'
            response_data['hint'] = 'This layer requires closer zoom'
        else:
            response_data['message'] = 'No features in this area'
            response_data['hint'] = 'Try panning to a different location'
    else:
        response_data['message'] = f'{len(geojson_features)} features'
        if len(geojson_features) == feature_limit:
            response_data['hint'] = f'Limited to {feature_limit} features'

    return JsonResponse(response_data)

@login_required
def layer_preview_status(request):
    """
    Quick endpoint to check if a layer is working without fetching features.
    Useful for showing layer status indicators.
    """
    layer_id = request.GET.get('layer_id')

    if not layer_id:
        return JsonResponse({'status': 'error', 'message': 'No layer ID provided'})

    try:
        layer = Layer.objects.select_related('server').get(layer_id=layer_id)

        if not layer.server:
            return JsonResponse({
                'status': 'error',
                'message': 'No server configured',
                'layer_name': layer.name
            })

        # Check if layer is accessible
        cache_key = f"layer_status_{layer_id}"
        cached_status = cache.get(cache_key)

        if cached_status:
            return JsonResponse(cached_status)

        # Quick check - just try to get layer info
        base_url = layer.server.url.rstrip('/')
        info_url = f"{base_url}/{layer.number}?f=json"

        try:
            response = requests.get(
                info_url,
                timeout=3,
                verify=False,
                headers={'User-Agent': 'Mozilla/5.0'}
            )

            if response.status_code == 200:
                data = response.json()
                if 'error' not in data:
                    status = {
                        'status': 'ok',
                        'message': 'Layer is accessible',
                        'layer_name': layer.name,
                        'geometry_type': data.get('geometryType'),
                        'has_features': True
                    }
                else:
                    status = {
                        'status': 'error',
                        'message': data['error'].get('message', 'Layer error'),
                        'layer_name': layer.name
                    }
            else:
                status = {
                    'status': 'error',
                    'message': f'HTTP {response.status_code}',
                    'layer_name': layer.name
                }

        except requests.exceptions.Timeout:
            status = {
                'status': 'slow',
                'message': 'Layer is slow to respond',
                'layer_name': layer.name
            }
        except Exception as e:
            status = {
                'status': 'error',
                'message': str(e)[:50],
                'layer_name': layer.name
            }

        # Cache status for 10 minutes
        cache.set(cache_key, status, 600)
        return JsonResponse(status)

    except Layer.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Layer not found'
        })

# @login_required
# @require_POST
# def export_dxf_multi(request):
#     """
#     Export selected layers as DXF file with advanced drawing features.
#     Fixed version with better debugging and error handling.
#     """
#     user = request.user
#     layer_ids = request.POST.getlist('layer_ids[]')
#     minx = request.POST.get('minx')
#     miny = request.POST.get('miny')
#     maxx = request.POST.get('maxx')
#     maxy = request.POST.get('maxy')
#     lat = request.POST.get('lat')
#     lng = request.POST.get('lng')
#
#     # Enhanced debug logging
#     logger.info(f"Export request from {user.username}: {len(layer_ids)} layers")
#     logger.debug(f"Bounds: ({minx}, {miny}) to ({maxx}, {maxy})")
#     logger.debug(f"Center: ({lat}, {lng})")
#
#     # Track processing status with more detail
#     processing_report = {
#         'attempted_layers': [],
#         'successful_layers': [],
#         'failed_layers': [],
#         'partial_layers': [],
#         'total_features': 0,
#         'errors': [],
#         'debug_info': []
#     }
#
#     if not layer_ids:
#         return JsonResponse({
#             'success': False,
#             'error': 'No layers selected'
#         }, status=200)  # Changed from 400 to 200
#
#     try:
#         # Validate and parse coordinates
#         try:
#             minx, miny = float(minx), float(miny)
#             maxx, maxy = float(maxx), float(maxy)
#         except (ValueError, TypeError) as e:
#             logger.error(f"Invalid coordinates: {e}")
#             return JsonResponse({
#                 'success': False,
#                 'error': f'Invalid coordinates: {str(e)}'
#             }, status=200)  # Changed from 400 to 200
#
#         # Parse optional center point
#         try:
#             if lat and lng:
#                 lat, lng = float(lat), float(lng)
#             else:
#                 lat = (miny + maxy) / 2
#                 lng = (minx + maxx) / 2
#         except (ValueError, TypeError) as e:
#             logger.warning(f"Error parsing center point, using calculated center: {e}")
#             lat = (miny + maxy) / 2
#             lng = (minx + maxx) / 2
#
#         # Enforce area limits
#         width = maxx - minx
#         height = maxy - miny
#         original_bounds = (minx, miny, maxx, maxy)
#
#         if width > MAX_DOWNLOAD_AREA * 2 or height > MAX_DOWNLOAD_AREA * 2:
#             minx = lng - MAX_DOWNLOAD_AREA
#             maxx = lng + MAX_DOWNLOAD_AREA
#             miny = lat - MAX_DOWNLOAD_AREA
#             maxy = lat + MAX_DOWNLOAD_AREA
#             logger.info(f"Area limited from {original_bounds} to ({minx}, {miny}, {maxx}, {maxy})")
#             processing_report['debug_info'].append(f"Area was limited to {MAX_DOWNLOAD_AREA} degrees")
#
#         # Get layers
#         try:
#             layers = Layer.objects.filter(layer_id__in=layer_ids).select_related('server')
#             if not layers.exists():
#                 return JsonResponse({
#                     'success': False,
#                     'error': 'No valid layers found in database'
#                 }, status=200)  # Changed from 404 to 200
#
#             logger.info(f"Found {layers.count()} layers in database")
#         except Exception as e:
#             logger.error(f"Database error fetching layers: {e}")
#             return JsonResponse({
#                 'success': False,
#                 'error': f'Database error: {str(e)}'
#             }, status=200)  # Changed from 500 to 200
#
#         # Check user connects (optional)
#         if hasattr(user, 'connects'):
#             if user.connects < len(layers):
#                 return JsonResponse({
#                     'success': False,
#                     'error': f'Not enough connects. Need {len(layers)}, you have {user.connects}'
#                 }, status=200)  # Changed from 403 to 200
#
#         # Create DXF document
#         try:
#             doc = ezdxf.new('R2010')
#             msp = doc.modelspace()
#             logger.debug("DXF document created successfully")
#         except Exception as e:
#             logger.error(f"Failed to create DXF document: {e}")
#             return JsonResponse({
#                 'success': False,
#                 'error': 'Failed to create DXF document'
#             }, status=200)
#
#         # Insert block definitions
#         try:
#             insert_blocks(doc)
#             logger.debug("Block definitions inserted")
#         except Exception as e:
#             logger.warning(f"Error inserting block definitions: {e}")
#             processing_report['errors'].append(f"Block definitions warning: {str(e)}")
#
#         # Determine spatial reference
#         try:
#             converter = GDA2020Converter()
#             out_sr_wkid = converter.get_wkid(lat, lng, datum='gda94')
#
#             if out_sr_wkid is None:
#                 out_sr_wkid = 28356  # Default to GDA94 MGA Zone 56
#                 logger.warning(f"Location {lat}, {lng} outside Australia, using default WKID 28356")
#                 processing_report['debug_info'].append(f"Using default WKID 28356")
#             else:
#                 logger.info(f"Using WKID {out_sr_wkid} for location {lat}, {lng}")
#                 processing_report['debug_info'].append(f"Using WKID {out_sr_wkid}")
#         except Exception as e:
#             logger.warning(f"Error determining spatial reference: {e}, using default")
#             out_sr_wkid = 28356
#             processing_report['debug_info'].append(f"WKID error, using default 28356")
#
#         # Process each layer
#         for layer in layers:
#             layer_name = layer.name
#             processing_report['attempted_layers'].append(layer_name)
#             layer_feature_count = 0
#             layer_errors = []
#
#             logger.info(f"Processing layer: {layer_name} (ID: {layer.layer_id}, Number: {layer.number})")
#
#             try:
#                 # Create layer in DXF
#                 try:
#                     if layer_name not in doc.layers:
#                         doc.layers.new(name=layer_name)
#                         logger.debug(f"Created DXF layer: {layer_name}")
#                 except Exception as e:
#                     logger.warning(f"Could not create DXF layer '{layer_name}': {e}")
#                     layer_errors.append(f"Layer creation warning: {str(e)}")
#
#                 # Create Text layer for labels
#                 try:
#                     if 'Text' not in doc.layers:
#                         doc.layers.new(name='Text')
#                 except:
#                     pass
#
#                 # Check if server exists
#                 if not layer.server:
#                     logger.error(f"No server configured for layer {layer_name}")
#                     layer_errors.append("No server configured")
#                     processing_report['failed_layers'].append({
#                         'name': layer_name,
#                         'errors': layer_errors
#                     })
#                     continue
#
#                 # Log the request we're about to make
#                 logger.debug(f"Fetching from: {layer.server.url}/{layer.number}")
#                 logger.debug(f"Bounds: {minx},{miny},{maxx},{maxy}")
#
#                 # Fetch features with detailed error tracking
#                 features_data = []
#                 try:
#                     features_data = fetch_layer_features_with_attributes(
#                         layer, minx, miny, maxx, maxy, out_sr=out_sr_wkid
#                     )
#
#                     if not features_data:
#                         logger.warning(f"No features returned for layer {layer_name}")
#                         layer_errors.append("No features in area")
#                     else:
#                         logger.info(f"Fetched {len(features_data)} features for layer {layer_name}")
#
#                 except requests.exceptions.Timeout:
#                     logger.error(f"Timeout fetching layer {layer_name}")
#                     layer_errors.append("Request timeout")
#                 except requests.exceptions.RequestException as e:
#                     logger.error(f"Network error for layer {layer_name}: {e}")
#                     layer_errors.append(f"Network error: {str(e)[:100]}")
#                 except Exception as e:
#                     logger.error(f"Error fetching layer {layer_name}: {e}", exc_info=True)
#                     layer_errors.append(f"Fetch error: {str(e)[:100]}")
#
#                 # Process each feature
#                 if features_data:
#                     for feature_index, feature_info in enumerate(features_data):
#                         try:
#                             geom = feature_info.get('geometry')
#                             if geom and geom.valid:
#                                 try:
#                                     # Use the safer drawing function
#                                     success = draw_feature_to_dxf_safe(
#                                         msp,
#                                         geom,
#                                         feature_info.get('attributes', {}),
#                                         layer
#                                     )
#                                     if success:
#                                         layer_feature_count += 1
#                                         processing_report['total_features'] += 1
#                                     else:
#                                         logger.debug(f"Failed to draw feature {feature_index} in {layer_name}")
#                                 except Exception as e:
#                                     logger.debug(f"Error drawing feature {feature_index} in {layer_name}: {e}")
#                                     if feature_index < 5:  # Only log first few errors
#                                         layer_errors.append(f"Feature {feature_index} draw error")
#                             else:
#                                 logger.debug(f"Invalid geometry for feature {feature_index} in {layer_name}")
#                         except Exception as e:
#                             logger.debug(f"Error processing feature {feature_index} in {layer_name}: {e}")
#                             continue
#
#                 # Categorize layer result
#                 if layer_feature_count > 0:
#                     if layer_errors:
#                         processing_report['partial_layers'].append({
#                             'name': layer_name,
#                             'features': layer_feature_count,
#                             'errors': layer_errors[:5]  # Limit error count
#                         })
#                     else:
#                         processing_report['successful_layers'].append({
#                             'name': layer_name,
#                             'features': layer_feature_count
#                         })
#
#                     # Log download record
#                     try:
#                         DownloadRecord.objects.create(
#                             user=user,
#                             layer=layer,
#                             latitude=lat,
#                             longitude=lng
#                         )
#                     except Exception as e:
#                         logger.warning(f"Could not create download record: {e}")
#                 else:
#                     processing_report['failed_layers'].append({
#                         'name': layer_name,
#                         'errors': layer_errors if layer_errors else ['No features found in area']
#                     })
#
#             except Exception as e:
#                 logger.error(f"Unexpected error processing layer {layer_name}: {e}", exc_info=True)
#                 processing_report['failed_layers'].append({
#                     'name': layer_name,
#                     'errors': [f"Unexpected error: {str(e)[:100]}"]
#                 })
#
#         # Log final summary
#         logger.info(
#             f"Export summary - Total features: {processing_report['total_features']}, "
#             f"Successful: {len(processing_report['successful_layers'])}, "
#             f"Partial: {len(processing_report['partial_layers'])}, "
#             f"Failed: {len(processing_report['failed_layers'])}"
#         )
#
#         # Check if we have any successful exports
#         if processing_report['total_features'] == 0:
#             # Return user-friendly error message
#             failed_names = [l['name'] for l in processing_report['failed_layers']]
#
#             return JsonResponse({
#                 'success': False,
#                 'error': 'No features could be exported from the selected area',
#                 'details': {
#                     'message': 'The selected layers may not have data in this area. Try zooming to a different location or selecting different layers.',
#                     'attempted_layers': len(processing_report['attempted_layers']),
#                     'failed_layers': failed_names[:10],  # Limit list size
#                     'suggestions': [
#                         'Zoom to a different area',
#                         'Select different layers',
#                         'Check if layers are properly configured',
#                         'Verify the area contains infrastructure'
#                     ]
#                 },
#                 'debug': processing_report['debug_info'] if settings.DEBUG else None
#             }, status=200)  # Important: Changed from 404 to 200
#
#         # Deduct connects only for successful/partial layers
#         successful_count = len(processing_report['successful_layers']) + len(processing_report['partial_layers'])
#         if hasattr(user, 'connects') and successful_count > 0:
#             try:
#                 user.connects -= successful_count
#                 user.save()
#                 logger.info(f"Deducted {successful_count} connects from user {user.username}")
#             except Exception as e:
#                 logger.error(f"Error updating user connects: {e}")
#
#         # Generate DXF file
#         try:
#             response = HttpResponse(content_type='application/dxf')
#             filename = f"export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
#             response['Content-Disposition'] = f'attachment; filename="{filename}"'
#
#             # Write DXF
#             doc.write(response)
#
#             logger.info(
#                 f"Successfully exported DXF for {user.username}: "
#                 f"{processing_report['total_features']} features from {successful_count} layers"
#             )
#
#             return response
#
#         except Exception as e:
#             logger.error(f"Error generating DXF response: {e}", exc_info=True)
#             return JsonResponse({
#                 'success': False,
#                 'error': 'Failed to generate DXF file'
#             }, status=200)
#
#     except Exception as e:
#         logger.error(f"Critical export error: {e}", exc_info=True)
#         return JsonResponse({
#             'success': False,
#             'error': 'Export failed unexpectedly',
#             'details': str(e) if settings.DEBUG else 'Please contact support'
#         }, status=200)

@login_required
@require_POST
def export_dxf_multi(request):
    """
    Optimized DXF export for Australian infrastructure analysis.
    Clean, efficient, and focused on delivering perfect CAD files.
    """

    # Parse request parameters
    layer_ids = request.POST.getlist('layer_ids[]')
    bounds = {
        'minx': float(request.POST.get('minx', 0)),
        'miny': float(request.POST.get('miny', 0)),
        'maxx': float(request.POST.get('maxx', 0)),
        'maxy': float(request.POST.get('maxy', 0))
    }

    # Calculate center point
    center_lng = (bounds['minx'] + bounds['maxx']) / 2
    center_lat = (bounds['miny'] + bounds['maxy']) / 2

    # Input validation
    if not layer_ids:
        return JsonResponse({'success': False, 'error': 'No layers selected'})

    # Enforce reasonable download area
    width = bounds['maxx'] - bounds['minx']
    height = bounds['maxy'] - bounds['miny']

    if width > MAX_DOWNLOAD_AREA * 2 or height > MAX_DOWNLOAD_AREA * 2:
        bounds = {
            'minx': center_lng - MAX_DOWNLOAD_AREA,
            'maxx': center_lng + MAX_DOWNLOAD_AREA,
            'miny': center_lat - MAX_DOWNLOAD_AREA,
            'maxy': center_lat + MAX_DOWNLOAD_AREA
        }

    try:
        # Get valid layers
        layers = Layer.objects.filter(
            layer_id__in=layer_ids,
            server__isnull=False
        ).select_related('server')

        if not layers:
            return JsonResponse({'success': False, 'error': 'No valid layers found'})

        # Check user permissions
        user = request.user
        if hasattr(user, 'connects') and user.connects < len(layers):
            return JsonResponse({
                'success': False,
                'error': f'Need {len(layers)} connects, you have {user.connects}'
            })

        # Create optimized DXF document
        doc = create_optimized_dxf()
        msp = doc.modelspace()

        # Determine proper coordinate system for Australia
        coordinate_system = get_australian_coordinate_system(center_lat, center_lng)

        # Process layers efficiently
        export_summary = process_layers_for_export(
            layers, bounds, msp, coordinate_system
        )

        # Check if we got any features
        if export_summary['total_features'] == 0:
            return JsonResponse({
                'success': False,
                'error': 'No infrastructure found in selected area',
                'suggestion': 'Try a different location or zoom out slightly'
            })

        # Deduct connects for successful export
        if hasattr(user, 'connects'):
            user.connects -= export_summary['successful_layers']
            user.save()

        # Log successful exports
        log_export_records(user, layers, center_lat, center_lng)

        # Generate and return DXF file
        response = HttpResponse(content_type='application/dxf')
        filename = f"infrastructure_{datetime.now().strftime('%Y%m%d_%H%M%S')}.dxf"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        doc.write(response)

        logger.info(f"Successfully exported {export_summary['total_features']} features "
                    f"from {export_summary['successful_layers']} layers for {user.username}")

        return response

    except Exception as e:
        logger.error(f"Export failed for {user.username}: {e}")
        return JsonResponse({
            'success': False,
            'error': 'Export failed. Please try again or contact support.'
        })


def create_optimized_dxf():
    """Create DXF document optimized for Australian infrastructure"""

    doc = ezdxf.new('R2010')  # Compatible with most CAD software

    # Set proper units and precision for Australian infrastructure
    doc.header['$INSUNITS'] = 6  # Meters
    doc.header['$LUNITS'] = 2  # Decimal
    doc.header['$LUPREC'] = 3  # 3 decimal places
    doc.header['$AUNITS'] = 0  # Decimal degrees
    doc.header['$AUPREC'] = 6  # 6 decimal places for angles

    # Add infrastructure-specific block definitions
    create_infrastructure_blocks(doc)

    return doc


def get_australian_coordinate_system(lat, lng):
    """Get appropriate Australian coordinate system"""

    converter = GDA2020Converter()

    # Use GDA2020 (current Australian standard)
    wkid = converter.get_wkid(lat, lng, datum='gda2020')

    if wkid is None:
        # Fallback based on longitude
        if 115.0 <= lng <= 117.0:  # Western Australia
            wkid = 7850  # GDA2020 Zone 50
        elif 144.0 <= lng <= 146.0:  # Victoria/Melbourne
            wkid = 7855  # GDA2020 Zone 55
        elif 150.0 <= lng <= 154.0:  # NSW/QLD Eastern
            wkid = 7856  # GDA2020 Zone 56
        else:
            wkid = 7855  # Default to Zone 55

    logger.info(f"Using coordinate system EPSG:{wkid} for location ({lat:.4f}, {lng:.4f})")
    return wkid


def process_layers_for_export(layers, bounds, msp, coordinate_system):
    """Process layers efficiently for export"""

    summary = {
        'total_features': 0,
        'successful_layers': 0,
        'failed_layers': []
    }

    for layer in layers:
        logger.info(f"Processing layer: {layer.name}")

        try:
            # Create DXF layer with proper naming
            layer_name = sanitize_layer_name(layer.name)
            if layer_name not in msp.doc.layers:
                dxf_layer = msp.doc.layers.new(name=layer_name)
                set_layer_properties(dxf_layer, layer)

            # Fetch features efficiently
            features = fetch_layer_features_with_attributes(
                layer,
                bounds['minx'], bounds['miny'], bounds['maxx'], bounds['maxy'],
                limit=MAX_FEATURES_PER_LAYER,
                out_sr=coordinate_system,
                preview_mode=False
            )

            if not features:
                logger.warning(f"No features found for {layer.name}")
                summary['failed_layers'].append(layer.name)
                continue

            # Draw features to DXF
            feature_count = 0
            for feature in features:
                if draw_infrastructure_feature(msp, feature, layer_name):
                    feature_count += 1

            if feature_count > 0:
                summary['total_features'] += feature_count
                summary['successful_layers'] += 1
                logger.info(f"Added {feature_count} features from {layer.name}")
            else:
                summary['failed_layers'].append(layer.name)

        except Exception as e:
            logger.error(f"Error processing layer {layer.name}: {e}")
            summary['failed_layers'].append(layer.name)

    return summary


def create_infrastructure_blocks(doc):
    """Create optimized block definitions for Australian infrastructure"""

    blocks = {
        'HYDRANT': {
            'entities': [
                ('circle', (0, 0), 0.3, colors.BLUE),
                ('text', 'FH', (0.4, 0.2), 0.3)
            ]
        },
        'VALVE': {
            'entities': [
                ('rectangle', (-0.3, -0.2), (0.3, 0.2), colors.BLUE),
                ('text', 'V', (0.4, 0.1), 0.25)
            ]
        },
        'MANHOLE': {
            'entities': [
                ('circle', (0, 0), 0.4, colors.GREEN),
                ('text', 'MH', (0.5, 0.2), 0.3)
            ]
        },
        'PIT': {
            'entities': [
                ('circle', (0, 0), 0.25, colors.CYAN),
                ('text', 'P', (0.3, 0.1), 0.25)
            ]
        },
        'POLE': {
            'entities': [
                ('circle', (0, 0), 0.2, colors.RED),
                ('text', 'EP', (0.3, 0.1), 0.25)
            ]
        }
    }

    for block_name, block_def in blocks.items():
        if block_name not in doc.blocks:
            block = doc.blocks.new(name=block_name)

            for entity in block_def['entities']:
                if entity[0] == 'circle':
                    block.add_circle(entity[1], entity[2], dxfattribs={'color': entity[3]})
                elif entity[0] == 'rectangle':
                    coords = [entity[1], (entity[2][0], entity[1][1]), entity[2], (entity[1][0], entity[2][1])]
                    block.add_lwpolyline(coords, close=True, dxfattribs={'color': entity[3]})
                elif entity[0] == 'text':
                    block.add_text(entity[1], dxfattribs={
                        'insert': entity[2],
                        'height': entity[3]
                    })


def sanitize_layer_name(name):
    """Clean layer names for DXF compatibility"""

    if not name:
        return "INFRASTRUCTURE"

    # Replace problematic characters
    sanitized = name.upper().replace(' ', '_').replace('-', '_')

    # Remove special characters
    allowed_chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_'
    sanitized = ''.join(c for c in sanitized if c in allowed_chars)

    # Ensure valid start
    if sanitized and sanitized[0].isdigit():
        sanitized = 'L_' + sanitized

    return sanitized[:31]  # DXF layer name limit


def set_layer_properties(dxf_layer, layer):
    """Set DXF layer properties based on infrastructure type"""

    layer_name_lower = layer.name.lower() if layer.name else ''

    # Set colors based on Australian infrastructure standards
    if any(word in layer_name_lower for word in ['water', 'drinking']):
        dxf_layer.dxf.color = colors.BLUE
    elif any(word in layer_name_lower for word in ['sewer', 'waste']):
        dxf_layer.dxf.color = colors.GREEN
    elif any(word in layer_name_lower for word in ['storm', 'drain']):
        dxf_layer.dxf.color = colors.CYAN
    elif any(word in layer_name_lower for word in ['electric', 'power']):
        dxf_layer.dxf.color = colors.RED
    elif any(word in layer_name_lower for word in ['gas']):
        dxf_layer.dxf.color = colors.YELLOW
    elif any(word in layer_name_lower for word in ['communication', 'telecom']):
        dxf_layer.dxf.color = colors.MAGENTA
    else:
        dxf_layer.dxf.color = colors.WHITE


def draw_infrastructure_feature(msp, feature, layer_name):
    """Draw infrastructure feature to DXF with proper attributes"""

    try:
        geometry = feature.get('geometry')
        attributes = feature.get('attributes', {})

        if not geometry or not geometry.valid:
            return False

        geom_type = geometry.geom_type

        if geom_type == 'Point':
            draw_infrastructure_point(msp, geometry, attributes, layer_name)

        elif geom_type == 'LineString':
            draw_infrastructure_line(msp, geometry, attributes, layer_name)

        elif geom_type == 'Polygon':
            draw_infrastructure_polygon(msp, geometry, attributes, layer_name)

        elif geom_type.startswith('Multi'):
            # Handle multi-geometries
            for geom_part in geometry:
                part_feature = {'geometry': geom_part, 'attributes': attributes}
                draw_infrastructure_feature(msp, part_feature, layer_name)

        return True

    except Exception as e:
        logger.debug(f"Error drawing feature: {e}")
        return False


def draw_infrastructure_point(msp, point, attributes, layer_name):
    """Draw infrastructure point with appropriate symbol"""

    x, y = point.x, point.y
    layer_name_lower = layer_name.lower()

    # Choose appropriate block
    if 'hydrant' in layer_name_lower:
        msp.add_blockref('HYDRANT', (x, y), dxfattribs={'layer': layer_name})
    elif 'valve' in layer_name_lower:
        msp.add_blockref('VALVE', (x, y), dxfattribs={'layer': layer_name})
    elif 'manhole' in layer_name_lower or 'maintenance' in layer_name_lower:
        msp.add_blockref('MANHOLE', (x, y), dxfattribs={'layer': layer_name})
    elif 'pit' in layer_name_lower:
        msp.add_blockref('PIT', (x, y), dxfattribs={'layer': layer_name})
    elif 'pole' in layer_name_lower or 'electric' in layer_name_lower:
        msp.add_blockref('POLE', (x, y), dxfattribs={'layer': layer_name})
    else:
        # Default point
        msp.add_circle((x, y), 0.2, dxfattribs={'layer': layer_name})

    # Add attribute labels
    add_infrastructure_labels(msp, (x, y), attributes, layer_name)


def draw_infrastructure_line(msp, linestring, attributes, layer_name):
    """Draw infrastructure line with labels"""

    coords = list(linestring.coords)
    if len(coords) < 2:
        return

    # Draw the line
    msp.add_lwpolyline(coords, dxfattribs={'layer': layer_name})

    # Add labels along the line
    label_text = extract_infrastructure_label(attributes)
    if label_text:
        add_line_labels(msp, coords, label_text, layer_name)


def draw_infrastructure_polygon(msp, polygon, attributes, layer_name):
    """Draw infrastructure polygon"""

    # Draw exterior
    exterior_coords = list(polygon.exterior.coords)
    if len(exterior_coords) >= 3:
        msp.add_lwpolyline(exterior_coords, close=True, dxfattribs={'layer': layer_name})

    # Draw holes
    for interior in polygon.interiors:
        interior_coords = list(interior.coords)
        if len(interior_coords) >= 3:
            msp.add_lwpolyline(interior_coords, close=True, dxfattribs={'layer': layer_name})


def extract_infrastructure_label(attributes):
    """Extract meaningful label from attributes"""

    labels = []

    # Check for diameter/size
    for key, value in attributes.items():
        key_lower = key.lower()
        if value is not None and isinstance(value, (int, float)) and value > 0:
            if 'diam' in key_lower:
                labels.append(f"Ø{int(value)}mm")
            elif 'width' in key_lower and value < 10:  # Assume meters if small
                labels.append(f"W{value:.1f}m")
            elif 'height' in key_lower and value < 10:
                labels.append(f"H{value:.1f}m")

    # Check for material
    for key, value in attributes.items():
        key_lower = key.lower()
        if 'material' in key_lower or 'mat' in key_lower:
            if value and isinstance(value, str):
                labels.append(str(value)[:10])  # Limit length

    return ' '.join(labels) if labels else None


def add_infrastructure_labels(msp, point, attributes, layer_name):
    """Add attribute labels near infrastructure points"""

    x, y = point
    label_text = extract_infrastructure_label(attributes)

    if label_text:
        msp.add_text(label_text, dxfattribs={
            'insert': (x + TEXT_OFFSET, y + TEXT_OFFSET),
            'height': TEXT_HEIGHT,
            'layer': layer_name
        })


def add_line_labels(msp, coords, label_text, layer_name):
    """Add labels along infrastructure lines"""

    if len(coords) < 2 or not label_text:
        return

    # Label at midpoint of longest segment
    max_length = 0
    mid_point = None

    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        length = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

        if length > max_length:
            max_length = length
            mid_point = ((x1 + x2) / 2, (y1 + y2) / 2)

    if mid_point and max_length > 1.0:  # Only label longer segments
        msp.add_text(label_text, dxfattribs={
            'insert': (mid_point[0], mid_point[1] + TEXT_HEIGHT),
            'height': TEXT_HEIGHT,
            'layer': layer_name
        })


def log_export_records(user, layers, lat, lng):
    """Log download records efficiently"""

    records = []
    for layer in layers:
        records.append(DownloadRecord(
            user=user,
            layer=layer,
            latitude=lat,
            longitude=lng
        ))

    # Bulk create for efficiency
    DownloadRecord.objects.bulk_create(records, ignore_conflicts=True)


# Additional utility function for better error handling
def validate_export_request(layer_ids, bounds, user):
    """Validate export request parameters"""

    errors = []

    if not layer_ids:
        errors.append("No layers selected")

    if not all(isinstance(coord, (int, float)) for coord in bounds.values()):
        errors.append("Invalid coordinate values")

    # Check bounds are reasonable
    width = bounds['maxx'] - bounds['minx']
    height = bounds['maxy'] - bounds['miny']

    if width <= 0 or height <= 0:
        errors.append("Invalid bounding box")

    if width > 1 or height > 1:  # Very large area
        errors.append("Selected area is too large")

    return errors
def draw_feature_to_dxf_safe(msp, geom, attributes, layer):
    """
    Safer version of draw_feature_to_dxf with additional error handling.
    Returns True if successful, False otherwise.
    """
    try:
        # Call the original function
        draw_feature_to_dxf(msp, geom, attributes, layer)
        return True
    except Exception as e:
        logger.debug(f"Error drawing feature for {layer.name}: {e}")
        return False


@login_required
@require_POST
def download_layers(request):
    """Handle layer download with result display"""
    layer_ids = request.POST.getlist('layer_ids[]')
    lat = float(request.POST.get('lat', 0))
    lng = float(request.POST.get('lng', 0))

    if not layer_ids:
        return TemplateResponse(request, 'partials/download_result.html', {
            'success': False,
            'error_message': 'No layers selected',
            'error_code': 'no_selection'
        })

    user = request.user

    # Check connects
    user_connects = getattr(user, 'connects', 0)
    if user_connects < len(layer_ids):
        return TemplateResponse(request, 'partials/download_result.html', {
            'success': False,
            'error_message': f'Insufficient connects',
            'error_code': 'insufficient_connects',
            'required_connects': len(layer_ids),
            'user_connects': user_connects
        })

    try:
        # Log downloads
        layers = Layer.objects.filter(layer_id__in=layer_ids)
        for layer in layers:
            DownloadRecord.objects.create(
                user=user,
                layer=layer,
                latitude=lat,
                longitude=lng
            )

        # Deduct connects
        if hasattr(user, 'connects'):
            user.connects -= len(layer_ids)
            user.save()

        return TemplateResponse(request, 'partials/download_result.html', {
            'success': True,
            'layer_count': len(layer_ids),
            'remaining_connects': getattr(user, 'connects', 0)
        })

    except Exception as e:
        logger.error(f"Download error: {e}")
        return TemplateResponse(request, 'partials/download_result.html', {
            'success': False,
            'error_message': 'Download failed. Please try again.',
            'error_code': 'server_error'
        })


@login_required
@require_GET
def layer_status_check(request):
    """Quick status check for layers - optional endpoint"""
    layer_id = request.GET.get('layer_id')

    if not layer_id:
        return JsonResponse({'status': 'error'})

    # For now, just return OK for all layers
    # You can enhance this later to actually check layer health
    return JsonResponse({
        'status': 'ok',
        'layer_id': layer_id
    })


@login_required
def nearby_layers(request):
    """Return layers near a point."""
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        dist = float(request.GET.get('dist', 2000))
    except (TypeError, ValueError):
        return JsonResponse({'error': 'Invalid coordinates'}, status=400)

    from django.contrib.gis.geos import Point
    from django.contrib.gis.db.models.functions import Distance

    point = Point(lng, lat, srid=4326)
    preferred_ids = set(UserLayerPreference.get_preferred_layer_ids(request.user))

    layers = Layer.objects.annotate(
        distance=Distance('geometry', point)
    ).filter(
        distance__lte=dist,
        geometry__isnull=False
    ).select_related('server').order_by('distance')[:20]

    data = []
    for layer in layers:
        data.append({
            'id': layer.layer_id,
            'name': layer.name,
            'type': layer.type,
            'server_name': layer.server.name if layer.server else 'Unknown',
            'distance_m': round(layer.distance.m, 1) if layer.distance else 0,
            'is_preferred': layer.layer_id in preferred_ids,
        })

    return JsonResponse(data, safe=False)

@login_required
def check_connects(request):
    """Check user's available connects"""
    connects = getattr(request.user, 'connects', 0)
    return JsonResponse({
        'connects': connects,
        'username': request.user.username
    })


# Helper functions

# def fetch_layer_features(layer, minx, miny, maxx, maxy, limit=2000, out_sr=4326):
#     """
#     Fetch features from ArcGIS REST service.
#     Returns list of GEOS geometries.
#     """
#     if not layer.server:
#         return []
#
#     # Handle offset points
#     if (layer.type == 'point' and
#             layer.offsetX is not None and layer.offsetY is not None and
#             layer.offsetX != 0 and layer.offsetY != 0):
#
#         if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
#             try:
#                 point = Point(layer.offsetX, layer.offsetY, srid=4326)
#                 return [point]
#             except:
#                 pass
#
#     # Build query URL
#     base_url = layer.server.url.rstrip('/')
#     url = f"{base_url}/{layer.number}/query"
#
#     params = {
#         'f': 'geojson',
#         'where': '1=1',
#         'geometry': f"{minx},{miny},{maxx},{maxy}",
#         'geometryType': 'esriGeometryEnvelope',
#         'spatialRel': 'esriSpatialRelIntersects',
#         'inSR': 4326,
#         'outSR': out_sr,
#         'returnGeometry': 'true',
#         'outFields': '*',
#         'maxRecordCount': limit
#     }
#
#     try:
#         response = requests.get(url, params=params, timeout=30)
#         response.raise_for_status()
#
#         data = response.json()
#
#         if 'error' in data:
#             logger.error(f"ArcGIS error for {layer.name}: {data['error']}")
#             return []
#
#         features = data.get('features', [])
#
#         geometries = []
#         for feature in features[:limit]:
#             geom_data = feature.get('geometry')
#             if geom_data:
#                 try:
#                     geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
#                     if geom.valid:
#                         geometries.append(geom)
#                 except:
#                     continue
#
#         return geometries
#
#     except requests.exceptions.Timeout:
#         logger.error(f"Timeout fetching features for {layer.name}")
#         return []
#     except requests.exceptions.RequestException as e:
#         logger.error(f"Request error for {layer.name}: {e}")
#         return []
#     except Exception as e:
#         logger.error(f"Failed to fetch features for {layer.name}: {e}")
#         return []
#
#
# def fetch_layer_features_with_attributes(layer, minx, miny, maxx, maxy, limit=2000, out_sr=28356):
#     """
#     Fetch features from ArcGIS REST service with full attribute data.
#     Enhanced version with better error handling and debugging.
#     Returns list of dicts with geometry and attributes.
#     """
#     if not layer.server:
#         logger.error(f"Layer {layer.name} has no server configured")
#         return []
#
#     # Build query URL for REST service
#     base_url = layer.server.url.rstrip('/')
#     url = f"{base_url}/{layer.number}/query"
#
#     # Log the request details for debugging
#     logger.debug(f"Fetching features from: {url}")
#     logger.debug(f"Layer: {layer.name} (ID: {layer.layer_id}, Number: {layer.number})")
#     logger.debug(f"Bounds: ({minx}, {miny}) to ({maxx}, {maxy})")
#     logger.debug(f"Output SR: {out_sr}")
#
#     # Build parameters
#     # params = {
#     #     'f': 'geojson',
#     #     'where': '1=1',
#     #     'geometry': f"{minx},{miny},{maxx},{maxy}",
#     #     'geometryType': 'esriGeometryEnvelope',
#     #     'spatialRel': 'esriSpatialRelIntersects',
#     #     'inSR': 4326,
#     #     'outSR': out_sr,
#     #     'returnGeometry': 'true',
#     #     'outFields': '*',
#     #     'maxRecordCount': limit
#     # }
#
#     params = {
#         'f': 'json',  # ← USE ESRI JSON FORMAT INSTEAD!
#         'where': '1=1',
#         'geometry': f"{minx},{miny},{maxx},{maxy}",
#         'geometryType': 'esriGeometryEnvelope',
#         'spatialRel': 'esriSpatialRelIntersects',
#         'inSR': '4326',  # Use string format
#         'outSR': str(out_sr),
#         'returnGeometry': 'true',
#         'outFields': '*',
#         'maxRecordCount': limit
#     }
#
#     # Add SSL bypass for legacy servers
#     if 'gislegacy' in url or 'scc.qld.gov.au' in url:
#         response = requests.get(url, params=params, timeout=30, verify=False)
#     else:
#         response = requests.get(url, params=params, timeout=30)
#
#     try:
#         # Make the request with headers
#         headers = {
#             'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
#             'Accept': 'application/json, text/plain, */*',
#             'Accept-Language': 'en-US,en;q=0.9',
#             'Cache-Control': 'no-cache',
#             'Pragma': 'no-cache'
#         }
#
#         response = requests.get(url, params=params, headers=headers, timeout=30)
#
#         # Log response status
#         logger.debug(f"Response status for {layer.name}: {response.status_code}")
#
#         # Check response status
#         if response.status_code != 200:
#             logger.error(f"HTTP {response.status_code} for layer {layer.name}: {response.text[:500]}")
#             return []
#
#         response.raise_for_status()
#
#         # Parse JSON response
#         try:
#             data = response.json()
#         except json.JSONDecodeError as e:
#             logger.error(f"Invalid JSON response for {layer.name}: {e}")
#             logger.debug(f"Response content: {response.text[:500]}")
#             return []
#
#         # Check for ArcGIS error response
#         if 'error' in data:
#             error_msg = data['error'].get('message', 'Unknown error')
#             error_code = data['error'].get('code', 'Unknown')
#             logger.error(f"ArcGIS error for {layer.name}: [{error_code}] {error_msg}")
#
#             # Common error handling
#             if 'Invalid or missing input parameters' in error_msg:
#                 logger.error(f"Invalid parameters for layer {layer.name}. Check layer configuration.")
#             elif 'Unauthorized' in error_msg or error_code == 403:
#                 logger.error(f"Unauthorized access to layer {layer.name}")
#             elif 'Layer not found' in error_msg:
#                 logger.error(f"Layer {layer.number} not found on server {layer.server.url}")
#
#             return []
#
#         # Extract features
#         features = data.get('features', [])
#
#         if not features:
#             logger.info(f"No features found for {layer.name} in the specified area")
#             # Check if it's because the area is outside the layer's extent
#             if 'extent' in data:
#                 extent = data['extent']
#                 logger.debug(f"Layer extent: {extent}")
#             return []
#
#         logger.info(f"Found {len(features)} features for {layer.name}")
#
#         # Process features
#         feature_results = []
#         valid_count = 0
#         invalid_count = 0
#
#         for idx, feature in enumerate(features[:limit]):
#             try:
#                 geom_data = feature.get('geometry')
#
#                 # Handle both 'properties' and 'attributes' keys
#                 attributes = feature.get('properties', {})
#                 if not attributes:
#                     attributes = feature.get('attributes', {})
#
#                 if not geom_data:
#                     logger.debug(f"Feature {idx} in {layer.name} has no geometry")
#                     invalid_count += 1
#                     continue
#
#                 # Create GEOS geometry
#                 try:
#                     # Handle different geometry formats
#                     if isinstance(geom_data, dict):
#                         geom_json = json.dumps(geom_data)
#                     else:
#                         geom_json = geom_data
#
#                     geom = GEOSGeometry(geom_json, srid=out_sr)
#
#                     if not geom.valid:
#                         logger.debug(f"Feature {idx} in {layer.name} has invalid geometry")
#                         invalid_count += 1
#                         continue
#
#                     # Apply layer offsets if configured (convert from meters to map units)
#                     if layer.offsetX or layer.offsetY:
#                         offset_x = (layer.offsetX or 0) / 1000  # Convert mm to meters if needed
#                         offset_y = (layer.offsetY or 0) / 1000
#
#                         if offset_x != 0 or offset_y != 0:
#                             geom = apply_geometry_offset(geom, offset_x, offset_y, out_sr)
#
#                     feature_results.append({
#                         'geometry': geom,
#                         'attributes': attributes or {}
#                     })
#                     valid_count += 1
#
#                 except Exception as e:
#                     logger.debug(f"Error creating geometry for feature {idx} in {layer.name}: {e}")
#                     invalid_count += 1
#                     continue
#
#             except Exception as e:
#                 logger.debug(f"Error processing feature {idx} in {layer.name}: {e}")
#                 invalid_count += 1
#                 continue
#
#         if invalid_count > 0:
#             logger.warning(f"Layer {layer.name}: {valid_count} valid, {invalid_count} invalid features")
#
#         return feature_results
#
#     except requests.exceptions.Timeout:
#         logger.error(f"Timeout fetching features for {layer.name} (30s exceeded)")
#         return []
#     except requests.exceptions.ConnectionError as e:
#         logger.error(f"Connection error for {layer.name}: {e}")
#         return []
#     except requests.exceptions.RequestException as e:
#         logger.error(f"Request error for {layer.name}: {e}")
#         return []
#     except Exception as e:
#         logger.error(f"Unexpected error fetching features for {layer.name}: {e}", exc_info=True)
#         return []

def create_session_with_retries(max_retries=3):
    """Create a requests session with retry strategy"""
    session = requests.Session()
    retry_strategy = Retry(
        total=max_retries,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"],
        backoff_factor=1
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


def parse_esri_geometry(geom_dict: Dict, srid: int = 4326) -> Optional[GEOSGeometry]:
    """Convert ESRI JSON geometry to GEOS geometry"""
    if not geom_dict:
        return None

    try:
        # Point geometry
        if 'x' in geom_dict and 'y' in geom_dict:
            return Point(float(geom_dict['x']), float(geom_dict['y']), srid=srid)

        # MultiPoint
        elif 'points' in geom_dict:
            points = []
            for p in geom_dict['points']:
                if isinstance(p, (list, tuple)) and len(p) >= 2:
                    points.append(Point(p[0], p[1], srid=srid))
            if points:
                return MultiPoint(points, srid=srid)

        # Polyline/LineString
        elif 'paths' in geom_dict:
            paths = geom_dict['paths']
            if not paths:
                return None

            lines = []
            for path in paths:
                if len(path) >= 2:
                    try:
                        line = LineString(path, srid=srid)
                        if line.valid:
                            lines.append(line)
                    except:
                        continue

            if len(lines) == 1:
                return lines[0]
            elif len(lines) > 1:
                return MultiLineString(lines, srid=srid)

        # Polygon
        elif 'rings' in geom_dict:
            rings = geom_dict['rings']
            if not rings:
                return None

            valid_rings = []
            for ring in rings:
                if len(ring) >= 3:
                    valid_rings.append(ring)

            if not valid_rings:
                return None

            try:
                if len(valid_rings) == 1:
                    poly = Polygon(valid_rings[0], srid=srid)
                else:
                    poly = Polygon(valid_rings[0], *valid_rings[1:], srid=srid)

                if poly.valid:
                    return poly
                else:
                    # Try to fix invalid polygon
                    return poly.buffer(0)
            except:
                try:
                    return Polygon(valid_rings[0], srid=srid)
                except:
                    return None

        # GeoJSON format
        elif 'type' in geom_dict and 'coordinates' in geom_dict:
            try:
                geom = GEOSGeometry(json.dumps(geom_dict), srid=srid)
                if geom.valid:
                    return geom
            except:
                pass

    except Exception as e:
        logger.debug(f"Error parsing ESRI geometry: {e}")

    return None


def fetch_layer_features_with_attributes(
        layer,
        minx: float,
        miny: float,
        maxx: float,
        maxy: float,
        limit: int = 2000,
        out_sr: int = 28356,
        use_cache: bool = True,
        preview_mode: bool = False
) -> List[Dict[str, Any]]:
    """
    Fetch features from ArcGIS REST service with maximum compatibility.
    Works with both modern and legacy servers including SCRC.
    """

    if not layer.server:
        logger.error(f"Layer {layer.name} has no server configured")
        return []

    # Adjust limit for preview mode
    if preview_mode:
        limit = min(limit, 500)

    base_url = layer.server.url.rstrip('/')
    layer_number = layer.number
    query_url = f"{base_url}/{layer_number}/query"

    # Determine server characteristics
    is_legacy = any(x in base_url.lower() for x in ['gislegacy', 'legacy', 'old'])
    is_scrc = 'scc.qld.gov.au' in base_url.lower()
    needs_ssl_bypass = is_legacy or is_scrc or 'https' in base_url

    # Create session
    session = create_session_with_retries()

    # Build headers
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Encoding': 'gzip, deflate',
        'Cache-Control': 'no-cache'
    }

    if is_scrc:
        headers['Referer'] = 'https://gislegacy.scc.qld.gov.au/'

    logger.info(f"Fetching features from: {query_url}")
    logger.info(f"Layer: {layer.name}, Bounds: ({minx},{miny}) to ({maxx},{maxy})")

    feature_results = []

    # SPECIAL HANDLING FOR SCRC - They don't support spatial queries
    if is_scrc or 'scc.qld.gov.au' in base_url.lower():
        logger.info("Using SCRC-specific query (no spatial filter)")

        params = {
            'f': 'json',
            'where': '1=1',
            'outFields': '*',
            'returnGeometry': 'true',
            'outSR': str(out_sr),
            'resultRecordCount': str(min(limit * 2, 2000))  # Get more, filter later
        }

        try:
            response = session.get(
                query_url,
                params=params,
                headers=headers,
                timeout=30,
                verify=False
            )

            if response.status_code == 200:
                data = response.json()

                if 'error' not in data:
                    features = data.get('features', [])

                    for feature in features:
                        try:
                            geom = parse_esri_geometry(feature.get('geometry'), srid=out_sr)

                            if geom and geom.valid:
                                # Filter by bounds client-side
                                if out_sr == 4326:
                                    # For WGS84, we can filter by bounds
                                    try:
                                        # Transform to WGS84 if needed for bounds check
                                        test_geom = geom if geom.srid == 4326 else geom.clone()
                                        if test_geom.srid != 4326:
                                            test_geom.transform(4326)

                                        bounds = test_geom.bounds
                                        # Check if geometry intersects with request bounds
                                        if (bounds[0] <= maxx and bounds[2] >= minx and
                                                bounds[1] <= maxy and bounds[3] >= miny):
                                            feature_results.append({
                                                'geometry': geom,
                                                'attributes': feature.get('attributes', {})
                                            })
                                    except:
                                        # If bounds check fails, include anyway
                                        feature_results.append({
                                            'geometry': geom,
                                            'attributes': feature.get('attributes', {})
                                        })
                                else:
                                    # For non-WGS84, include all (can't easily filter)
                                    feature_results.append({
                                        'geometry': geom,
                                        'attributes': feature.get('attributes', {})
                                    })

                                if len(feature_results) >= limit:
                                    break

                        except Exception as e:
                            logger.debug(f"Error processing SCRC feature: {e}")
                            continue

                    logger.info(f"SCRC query returned {len(feature_results)} features")
                    return feature_results[:limit]
                else:
                    logger.error(f"SCRC query error: {data['error']}")

        except Exception as e:
            logger.error(f"SCRC query failed: {e}")

    # STANDARD QUERY STRATEGIES FOR NON-SCRC SERVERS
    strategies = [
        {
            'name': 'ESRI JSON with envelope',
            'params': {
                'f': 'json',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'inSR': '4326',
                'outSR': str(out_sr),
                'returnGeometry': 'true',
                'outFields': '*',
                'returnDistinctValues': 'false',
                'returnIdsOnly': 'false',
                'returnCountOnly': 'false',
                'maxRecordCount': str(limit),
                'resultRecordCount': str(limit)
            }
        },
        {
            'name': 'Simplified ESRI JSON',
            'params': {
                'f': 'json',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'returnGeometry': 'true',
                'outFields': '*'
            }
        },
        {
            'name': 'GeoJSON format',
            'params': {
                'f': 'geojson',
                'where': '1=1',
                'geometry': f'{minx},{miny},{maxx},{maxy}',
                'geometryType': 'esriGeometryEnvelope',
                'spatialRel': 'esriSpatialRelIntersects',
                'inSR': 4326,
                'outSR': out_sr,
                'returnGeometry': 'true',
                'outFields': '*',
                'maxRecordCount': limit
            }
        },
        {
            'name': 'No spatial filter',
            'params': {
                'f': 'json',
                'where': '1=1',
                'returnGeometry': 'true',
                'outFields': '*',
                'outSR': str(out_sr),
                'resultRecordCount': str(min(100, limit))
            }
        }
    ]

    # Try each strategy
    for strategy in strategies:
        if feature_results:  # Already got results from SCRC handling
            break

        try:
            logger.debug(f"Trying strategy: {strategy['name']}")

            verify_ssl = not needs_ssl_bypass
            response = session.get(
                query_url,
                params=strategy['params'],
                headers=headers,
                timeout=15 if preview_mode else 30,
                verify=verify_ssl
            )

            if response.status_code != 200:
                logger.debug(f"HTTP {response.status_code} for {strategy['name']}")
                continue

            try:
                data = response.json()
            except json.JSONDecodeError:
                continue

            if 'error' in data:
                error_msg = data['error'].get('message', 'Unknown')
                logger.debug(f"Server error: {error_msg}")
                if 'does not exist' in error_msg.lower():
                    break  # Layer doesn't exist
                continue

            # Process features
            if strategy['params']['f'] == 'geojson':
                # GeoJSON format
                features = data.get('features', [])
                for feature in features[:limit]:
                    try:
                        geom_data = feature.get('geometry')
                        if geom_data:
                            geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
                            if geom and geom.valid:
                                feature_results.append({
                                    'geometry': geom,
                                    'attributes': feature.get('properties', {})
                                })
                    except:
                        continue
            else:
                # ESRI JSON format
                features = data.get('features', [])
                for feature in features[:limit]:
                    try:
                        geom = parse_esri_geometry(
                            feature.get('geometry'),
                            srid=out_sr
                        )

                        if geom and geom.valid:
                            feature_results.append({
                                'geometry': geom,
                                'attributes': feature.get('attributes', {})
                            })
                    except:
                        continue

            if feature_results:
                logger.info(f"Got {len(feature_results)} features using {strategy['name']}")
                break

            if 'features' in data and isinstance(data['features'], list):
                logger.info(f"No features in area for {layer.name}")
                break

        except requests.exceptions.Timeout:
            if preview_mode:
                break
            continue
        except Exception as e:
            logger.debug(f"Strategy {strategy['name']} failed: {e}")
            continue

    if not feature_results:
        logger.warning(f"All strategies failed for {layer.name}")

    return feature_results[:limit]


def fetch_layer_features(layer, minx, miny, maxx, maxy, limit=2000, out_sr=4326):
    """Simplified version for backward compatibility"""
    features_with_attrs = fetch_layer_features_with_attributes(
        layer, minx, miny, maxx, maxy, limit, out_sr, preview_mode=True
    )
    return [f['geometry'] for f in features_with_attrs if f.get('geometry')]

def get_layer_metadata(base_url: str, layer_number: int) -> Optional[Dict]:
    """
    Get layer metadata from the service.
    Helps determine capabilities and optimize queries.
    """
    try:
        layer_url = f"{base_url}/{layer_number}"
        response = requests.get(
            f"{layer_url}?f=json",
            timeout=5,
            verify=False,
            headers={'User-Agent': 'Mozilla/5.0'}
        )

        if response.status_code == 200:
            data = response.json()
            if 'error' not in data:
                return {
                    'name': data.get('name'),
                    'geometryType': data.get('geometryType'),
                    'extent': data.get('extent'),
                    'capabilities': data.get('capabilities', '').split(','),
                    'maxRecordCount': data.get('maxRecordCount', 1000),
                    'supportedQueryFormats': data.get('supportedQueryFormats', 'JSON'),
                    'supportsCoordinatesQuantization': data.get('supportsCoordinatesQuantization', False),
                    'hasZ': data.get('hasZ', False),
                    'hasM': data.get('hasM', False)
                }
    except:
        pass
    return None


def fetch_layer_features(layer, minx, miny, maxx, maxy, limit=2000, out_sr=4326):
    """
    Simplified version for preview - returns just geometries.
    This is for backward compatibility.
    """
    features_with_attrs = fetch_layer_features_with_attributes(
        layer, minx, miny, maxx, maxy, limit, out_sr,
        preview_mode=True  # Optimize for preview
    )

    # Extract just the geometries
    return [f['geometry'] for f in features_with_attrs if f.get('geometry')]
def apply_geometry_offset(geom, offset_x, offset_y, srid):
    """
    Apply offset to geometry based on type.
    """
    try:
        geom_type = geom.geom_type

        if geom_type == 'Point':
            return Point(geom.x + offset_x, geom.y + offset_y, srid=srid)

        elif geom_type == 'LineString':
            coords = [(x + offset_x, y + offset_y) for x, y in geom.coords]
            return GEOSGeometry(f'LINESTRING({" ".join([f"{x} {y}" for x, y in coords])})', srid=srid)

        elif geom_type == 'Polygon':
            # Offset exterior ring
            exterior_coords = [(x + offset_x, y + offset_y) for x, y in geom.exterior.coords]

            # Handle interior rings (holes)
            if geom.num_interior_rings > 0:
                # This is more complex, need to handle holes
                wkt = f'POLYGON(({" ".join([f"{x} {y}" for x, y in exterior_coords])})'
                for interior in geom.interiors:
                    interior_coords = [(x + offset_x, y + offset_y) for x, y in interior.coords]
                    wkt += f', ({" ".join([f"{x} {y}" for x, y in interior_coords])})'
                wkt += ')'
                return GEOSGeometry(wkt, srid=srid)
            else:
                return GEOSGeometry(
                    f'POLYGON(({" ".join([f"{x} {y}" for x, y in exterior_coords])}))',
                    srid=srid
                )

        elif geom_type.startswith('Multi'):
            # Handle multi-geometries recursively
            parts = []
            for part in geom:
                offset_part = apply_geometry_offset(part, offset_x, offset_y, srid)
                parts.append(offset_part)

            # Combine back into multi-geometry
            if geom_type == 'MultiPoint':
                return MultiPoint(parts, srid=srid)
            elif geom_type == 'MultiLineString':
                return MultiLineString(parts, srid=srid)
            elif geom_type == 'MultiPolygon':
                return MultiPolygon(parts, srid=srid)

        # If we can't handle it, return original
        return geom

    except Exception as e:
        logger.debug(f"Error applying offset to geometry: {e}")
        return geom


def get_candidate_layers(lat, lng, selected_layer_ids):
    """Get candidate layers based on context"""

    if selected_layer_ids and selected_layer_ids[0]:
        try:
            selected = Layer.objects.get(layer_id=selected_layer_ids[0])

            # Find similar layers
            candidates = Layer.objects.filter(
                Q(type=selected.type) |
                Q(name__icontains=selected.name.split()[0] if selected.name else '')
            ).select_related('server')[:15]

            return candidates

        except Layer.DoesNotExist:
            pass

    # Default: return popular layer types
    popular_keywords = ['water', 'sewer', 'electric', 'road', 'property']
    query = Q()
    for keyword in popular_keywords:
        query |= Q(name__icontains=keyword)

    return Layer.objects.filter(
        query,
        server__isnull=False
    ).select_related('server')[:20]


def calculate_mock_distance(lat, lng, layer):
    """Calculate mock distance for demonstration"""
    import random

    # Prioritize certain layer types
    if layer.name:
        name_lower = layer.name.lower()
        if 'water' in name_lower or 'sewer' in name_lower:
            return random.randint(50, 500)
        elif 'electric' in name_lower:
            return random.randint(100, 600)
        elif 'road' in name_lower:
            return random.randint(150, 700)

    return random.randint(300, 1500)


def get_selection_context(selected_layer_ids):
    """Get context description based on selected layers"""
    if not selected_layer_ids or not selected_layer_ids[0]:
        return None

    try:
        layer = Layer.objects.get(layer_id=selected_layer_ids[0])
        name_lower = layer.name.lower() if layer.name else ''

        if any(word in name_lower for word in ['water', 'sewer', 'hydrant']):
            return 'water infrastructure'
        elif any(word in name_lower for word in ['electric', 'power', 'pole']):
            return 'electrical infrastructure'
        elif any(word in name_lower for word in ['road', 'street', 'footpath']):
            return 'road infrastructure'
        else:
            return f'{layer.type} infrastructure'

    except Layer.DoesNotExist:
        return None


# DXF Drawing Functions

def insert_blocks(doc):
    """Insert block definitions for special features"""

    # Valve block
    valve_block = doc.blocks.new(name='valve')
    valve_block.add_lwpolyline([(-0.5, -0.25), (-0.5, 0.25), (0.5, 0.25), (0.5, -0.25)], close=True)
    valve_block.add_solid([(-0.5, -0.25), (-0.5, 0.25), (0.5, 0.25), (0.5, -0.25)],
                          dxfattribs={'color': colors.BLACK})

    # Hydrant block
    hydrant_block = doc.blocks.new(name='hydrant')
    hydrant_block.add_circle((0, 0), radius=0.25, dxfattribs={'color': colors.BLACK})
    hydrant_block.add_text('FH', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Electric pillar block
    elec_pillar_block = doc.blocks.new(name='elec_pillar')
    elec_pillar_block.add_lwpolyline([(-0.5, -0.5), (-0.5, 0.5), (0.5, 0.5), (0.5, -0.5)], close=True)
    elec_pillar_block.add_text('EP', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Electric pole block
    elec_pole_block = doc.blocks.new(name='elec_pole')
    elec_pole_block.add_circle((0, 0), radius=0.25, dxfattribs={'color': colors.BLACK})
    elec_pole_block.add_text('PP', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Maintenance hole block
    maintenance_hole_block = doc.blocks.new(name='maintenance_hole')
    maintenance_hole_block.add_circle((0, 0), radius=0.525, dxfattribs={'color': colors.BLACK})
    maintenance_hole_block.add_text('MH', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })

    # Maintenance shaft block
    maintenance_shaft_block = doc.blocks.new(name='maintenance_shaft')
    maintenance_shaft_block.add_circle((0, 0), radius=0.3, dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_line((-0.21213, -0.21213), (0.21213, 0.21213),
                                     dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_line((-0.21213, 0.21213), (0.21213, -0.21213),
                                     dxfattribs={'color': colors.BLACK})
    maintenance_shaft_block.add_text('MS', dxfattribs={
        'insert': (TEXT_OFFSET_X, TEXT_OFFSET_Y),
        'height': TEXT_HEIGHT
    })


def line_length(x1, y1, x2, y2):
    """Calculate the length of a line segment"""
    dx = x2 - x1
    dy = y2 - y1
    return math.sqrt(dx ** 2 + dy ** 2)


def label_line(msp, x1, y1, x2, y2, label, offset=TEXT_HEIGHT / 2, text_readability=True, layer_name='Text'):
    """
    Draws a text label parallel to a line segment, positioned preferentially
    above or to the left of the line.
    """
    # Calculate line properties
    dx = x2 - x1
    dy = y2 - y1
    mid_x = (x1 + x2) / 2.0
    mid_y = (y1 + y2) / 2.0

    # Calculate angle in degrees (-180 to 180)
    angle_rad = math.atan2(dy, dx)
    angle_deg = math.degrees(angle_rad)

    # Handle zero-length lines
    segment_length = math.sqrt(dx ** 2 + dy ** 2)
    if segment_length == 0:
        logger.debug(f"Warning: Line for label '{label}' has zero length.")
        return

    # Determine Offset Direction (Prefer Above or Left)
    # Calculate a perpendicular vector (rotated +90 degrees counter-clockwise from line vector)
    perp_dx = -dy
    perp_dy = dx

    # Normalize the perpendicular vector
    norm = math.sqrt(perp_dx ** 2 + perp_dy ** 2)
    norm_perp_dx = perp_dx / norm
    norm_perp_dy = perp_dy / norm

    # Check the direction of the perpendicular vector
    tolerance = 1e-9
    is_pointing_up = norm_perp_dy > tolerance
    is_horizontal_pointing_left = abs(norm_perp_dy) <= tolerance and norm_perp_dx < -tolerance

    # If the default perpendicular direction is not Up or Left, flip it
    if not (is_pointing_up or is_horizontal_pointing_left):
        norm_perp_dx = -norm_perp_dx
        norm_perp_dy = -norm_perp_dy

    # Calculate final text position
    text_x = mid_x + (offset * norm_perp_dx)
    text_y = mid_y + (offset * norm_perp_dy)

    # Determine text angle and alignment
    text_angle = angle_deg

    # Optional: Adjust angle for better readability (avoid upside-down text)
    if text_readability:
        if 90 < abs(text_angle) <= 180:
            adjusted_angle = text_angle + 180
            text_angle = (adjusted_angle + 180) % 360 - 180

    # Create text layer if it doesn't exist
    try:
        doc = msp.doc
        if layer_name not in doc.layers:
            doc.layers.new(name=layer_name)
    except:
        pass

    # Place the text
    msp.add_text(
        text=label,
        dxfattribs={
            'insert': (0, 0, 0),  # Base point (required but not used for aligned text)
            'align_point': (text_x, text_y, 0),  # Actual alignment point
            'height': TEXT_HEIGHT,
            'rotation': text_angle,
            'layer': layer_name,
            'halign': 1,  # Center horizontal alignment
            'valign': 1  # Center vertical alignment
        }
    )


def draw_feature_to_dxf(msp, geom, attributes, layer):
    """
    Draw a feature to DXF with advanced attributes and labeling.
    """
    attrs = {'layer': layer.name}

    # Extract attributes for labeling
    label = ''
    size = ''
    material = ''
    width = 0
    inverts = ''
    elevation = None

    for k, v in attributes.items():
        if v is None:
            continue

        k_lower = k.lower()

        # Diameter/Width handling
        if 'diam' in k_lower or 'width' in k_lower:
            if isinstance(v, (int, float)):
                if width == 0:  # Don't override existing width
                    width = round(v / 1000, DECIMAL)
                if 'diam' in k_lower and int(v) != 0:
                    size = size + '%%C' + str(int(v))
                elif 'width' in k_lower and int(v) != 0:
                    if width < 1:
                        size = size + str(int(width * 1000)) + 'x'
                    else:
                        size = size + str(width) + 'x'

        # Height handling
        if 'height' in k_lower:
            if isinstance(v, (int, float)) and int(v) != 0:
                size = size + str(round(v / 1000, DECIMAL))

        # Elevation handling
        if 'elev' in k_lower or 'alti' in k_lower:
            if isinstance(v, (int, float)):
                elevation = round(v, DECIMAL)

        # Material handling
        if 'mat' in k_lower:
            material = str(v)

        # Invert levels
        if 'usil' in k_lower:
            if isinstance(v, (int, float)) and int(v) != 0:
                inverts = inverts + ' USIL ' + str(round(v, DECIMAL))
        if 'dsil' in k_lower:
            if isinstance(v, (int, float)) and int(v) != 0:
                inverts = inverts + ' DSIL ' + str(round(v, DECIMAL))

    label = (size + ' ' + material).strip()

    # Set line width attribute if we have a width
    if width > 0:
        attrs['const_width'] = width

    try:
        geom_type = geom.geom_type

        if geom_type == 'Point':
            x, y = geom.x, geom.y
            layer_name_lower = layer.name.lower()

            # Use appropriate block based on layer name
            if 'hydrant' in layer_name_lower:
                msp.add_blockref('hydrant', (x, y), dxfattribs={'layer': layer.name})
            elif 'valve' in layer_name_lower:
                msp.add_blockref('valve', (x, y), dxfattribs={'layer': layer.name})
            elif 'pillar' in layer_name_lower:
                msp.add_blockref('elec_pillar', (x, y), dxfattribs={'layer': layer.name})
            elif 'pole' in layer_name_lower:
                msp.add_blockref('elec_pole', (x, y), dxfattribs={'layer': layer.name})
            elif 'maintenance' in layer_name_lower:
                # Handle maintenance holes/shafts with diameter info
                i = 0
                for k, v in attributes.items():
                    if isinstance(v, (int, float)):
                        if 'diam' in k.lower():
                            if v > 600:  # Greater than 600mm
                                msp.add_blockref('maintenance_hole', (x, y), dxfattribs={'layer': layer.name})
                            else:
                                msp.add_blockref('maintenance_shaft', (x, y), dxfattribs={'layer': layer.name})
                            msp.add_text('%%C ' + str(round(v, DECIMAL)), dxfattribs={
                                'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                'height': TEXT_HEIGHT,
                                'layer': layer.name
                            })
                            i += 1
                        if 'sl' in k.lower():
                            msp.add_text('SL ' + str(round(v, DECIMAL)), dxfattribs={
                                'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                'height': TEXT_HEIGHT,
                                'layer': layer.name
                            })
                            i += 1
                        if 'il' in k.lower():
                            msp.add_text('IL ' + str(round(v, DECIMAL)), dxfattribs={
                                'insert': (x + TEXT_OFFSET_X, y - (i * TEXT_OFFSET_Y)),
                                'height': TEXT_HEIGHT,
                                'layer': layer.name
                            })
                            i += 1
            else:
                # Default point
                msp.add_point((x, y), dxfattribs={'layer': layer.name})

        elif geom_type == 'LineString':
            coords = list(geom.coords)
            if len(coords) >= 2:
                # Add labels if present
                if label:
                    for i in range(len(coords) - 1):
                        if line_length(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]) > 2:
                            label_line(msp, coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1],
                                       label, offset=(TEXT_HEIGHT + width) / 2)

                # Add invert labels if present
                if inverts:
                    for i in range(len(coords) - 1):
                        if line_length(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]) > 2:
                            label_line(msp, coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1],
                                       inverts, offset=-2.0 * (TEXT_HEIGHT + width / 2))

                # Create polyline
                lwpoly = msp.add_lwpolyline(coords, dxfattribs=attrs)
                if elevation is not None:
                    lwpoly.dxf.elevation = elevation

        elif geom_type == 'Polygon':
            # Draw exterior ring
            coords = list(geom.exterior.coords)
            if len(coords) >= 3:
                # Add labels if present
                if label:
                    for i in range(len(coords) - 1):
                        if line_length(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]) > 2:
                            label_line(msp, coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1],
                                       label, offset=TEXT_HEIGHT / 2)

                # Create closed polyline
                lwpoly = msp.add_lwpolyline(coords, close=True, dxfattribs=attrs)
                if elevation is not None:
                    lwpoly.dxf.elevation = elevation

            # Draw holes
            for interior in geom.interiors:
                coords = list(interior.coords)
                if len(coords) >= 3:
                    msp.add_lwpolyline(coords, close=True, dxfattribs=attrs)

        elif geom_type == 'MultiPoint':
            for point in geom:
                draw_feature_to_dxf(msp, point, attributes, layer)

        elif geom_type == 'MultiLineString':
            for line in geom:
                draw_feature_to_dxf(msp, line, attributes, layer)

        elif geom_type == 'MultiPolygon':
            for poly in geom:
                draw_feature_to_dxf(msp, poly, attributes, layer)

    except Exception as e:
        logger.error(f"Error drawing {geom_type}: {e}")