import json
import requests
import ezdxf
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.gis.geos import Point, Polygon, GEOSGeometry
from django.contrib.gis.db.models.functions import Distance
from django.db.models import Q
from .models import Layer, DownloadRecord, Server

# Simple logger setup
import logging

logger = logging.getLogger(__name__)

# Constants
OFFSET_DEG = 0.01  # ~1km envelope for queries
MAX_FEATURES_PREVIEW = 500  # Limit preview features


@login_required
def home(request):
    """Render the main map page"""
    return render(request, "home.html")


@login_required
def all_layers(request):
    """
    Return all layers with basic information.
    Simplified response for layer panel.
    """
    layers = Layer.objects.select_related('server').all().order_by('server__name', 'name')

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
            'centroid_lng': centroid_lng
        })

    return JsonResponse(data, safe=False)


@login_required
def layer_preview_features(request):
    """
    Get features for layer preview within bounds.
    Returns GeoJSON for rendering on map.
    """
    layer_id = request.GET.get('layer_id')
    minx = request.GET.get('minx')
    miny = request.GET.get('miny')
    maxx = request.GET.get('maxx')
    maxy = request.GET.get('maxy')

    if not all([layer_id, minx, miny, maxx, maxy]):
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    try:
        layer = get_object_or_404(Layer, layer_id=layer_id)
        minx, miny, maxx, maxy = float(minx), float(miny), float(maxx), float(maxy)

        # Simple area check
        area = (maxx - minx) * (maxy - miny)
        if area > 0.5:  # ~50km x 50km
            return JsonResponse({
                'type': 'FeatureCollection',
                'features': [],
                'message': 'Area too large. Please zoom in.'
            })

        # Fetch features from REST service
        features = fetch_layer_features(layer, minx, miny, maxx, maxy)

        # Convert to GeoJSON
        geojson_features = []
        for geom in features[:MAX_FEATURES_PREVIEW]:
            if geom and geom.valid:
                try:
                    feature = {
                        'type': 'Feature',
                        'geometry': json.loads(geom.geojson),
                        'properties': {
                            'layer_name': layer.name,
                            'layer_type': layer.type
                        }
                    }
                    geojson_features.append(feature)
                except:
                    continue

        return JsonResponse({
            'type': 'FeatureCollection',
            'features': geojson_features
        })

    except Exception as e:
        logger.error(f"Preview error: {e}")
        return JsonResponse({'error': 'Failed to load preview'}, status=500)


@login_required
def nearby_layers(request):
    """
    Return layers near a point with distance information.
    Enhanced to find more layers including those with offset coordinates.
    """
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        dist = float(request.GET.get('dist', 2000))  # Default 2km radius
    except (TypeError, ValueError):
        return JsonResponse([], safe=False)

    # Create point for distance calculation
    point = Point(lng, lat, srid=4326)

    # First try to find layers with geometry within distance
    layers_with_geom = Layer.objects.annotate(
        distance=Distance('geometry', point)
    ).filter(
        distance__lte=dist,
        geometry__isnull=False
    ).select_related('server')

    # Also find point layers that might only have offset coordinates
    # Create a bounding box for the search area
    from django.db.models import Q
    import math

    # Rough conversion: 1 degree ≈ 111km
    degree_offset = dist / 111000.0

    layers_with_offset = Layer.objects.filter(
        Q(type='point') &
        Q(offsetX__gte=lng - degree_offset) &
        Q(offsetX__lte=lng + degree_offset) &
        Q(offsetY__gte=lat - degree_offset) &
        Q(offsetY__lte=lat + degree_offset) &
        Q(offsetX__isnull=False) &
        Q(offsetY__isnull=False) &
        ~Q(offsetX=0, offsetY=0)
    ).select_related('server')

    # Combine both querysets
    all_layers = list(layers_with_geom) + list(layers_with_offset)
    # Remove duplicates
    seen = set()
    unique_layers = []
    for layer in all_layers:
        if layer.layer_id not in seen:
            seen.add(layer.layer_id)
            unique_layers.append(layer)

    data = []
    for layer in unique_layers[:30]:  # Limit to 30 nearest
        try:
            # Calculate distance and centroid
            if hasattr(layer, 'distance') and layer.distance:
                distance_m = round(layer.distance.m, 1)
                if layer.geometry:
                    centroid = layer.geometry.centroid
                    layer_lat, layer_lng = centroid.y, centroid.x
                else:
                    layer_lat, layer_lng = layer.offsetY, layer.offsetX
            else:
                # For offset-only layers, calculate distance manually
                if layer.offsetX and layer.offsetY:
                    layer_lat, layer_lng = layer.offsetY, layer.offsetX
                    # Simple distance calculation
                    dx = (lng - layer_lng) * 111000 * math.cos(math.radians(lat))
                    dy = (lat - layer_lat) * 111000
                    distance_m = round(math.sqrt(dx * dx + dy * dy), 1)
                else:
                    continue

            # Skip if distance is too far (double-check)
            if distance_m > dist:
                continue

            data.append({
                'id': layer.layer_id,
                'name': layer.name,
                'type': layer.type,
                'server_name': layer.server.name if layer.server else 'Unknown',
                'lat': layer_lat,
                'lng': layer_lng,
                'distance_m': distance_m
            })
        except Exception as e:
            logger.debug(f"Error processing layer {layer.layer_id}: {e}")
            continue

    # Sort by distance
    data.sort(key=lambda x: x['distance_m'])

    return JsonResponse(data[:20], safe=False)  # Return top 20


@login_required
@csrf_exempt
@require_POST
def export_dxf_multi(request):
    """
    Export selected layers as DXF file.
    Simplified version with basic error handling.
    """
    user = request.user
    layer_ids = request.POST.getlist('layer_ids[]')
    minx = request.POST.get('minx')
    miny = request.POST.get('miny')
    maxx = request.POST.get('maxx')
    maxy = request.POST.get('maxy')

    # Optional center point for download record
    lat = request.POST.get('lat')
    lng = request.POST.get('lng')

    if not layer_ids:
        return JsonResponse({'error': 'No layers selected'}, status=400)

    try:
        # Parse bounds
        minx, miny = float(minx), float(miny)
        maxx, maxy = float(maxx), float(maxy)

        # Parse optional center point
        if lat and lng:
            lat, lng = float(lat), float(lng)
        else:
            # Calculate center from bounds
            lat = (miny + maxy) / 2
            lng = (minx + maxx) / 2

        # Check area size
        area = (maxx - minx) * (maxy - miny)
        if area > 1.0:  # ~100km x 100km
            return JsonResponse({
                'error': 'Area too large. Please zoom in to a smaller area.'
            }, status=400)

        # Get layers
        layers = Layer.objects.filter(layer_id__in=layer_ids).select_related('server')

        if not layers.exists():
            return JsonResponse({'error': 'No valid layers found'}, status=404)

        # Check user connects if applicable
        if hasattr(user, 'connects'):
            if user.connects < len(layers):
                return JsonResponse({
                    'error': f'Not enough connects. Need {len(layers)}, you have {user.connects}'
                }, status=403)

        # Create DXF
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()

        exported_count = 0
        successful_layers = []

        for layer in layers:
            # Fetch features
            features = fetch_layer_features(layer, minx, miny, maxx, maxy)

            layer_feature_count = 0
            for geom in features:
                if geom and geom.valid:
                    draw_geometry_to_dxf(msp, geom, layer.name)
                    layer_feature_count += 1
                    exported_count += 1

            if layer_feature_count > 0:
                successful_layers.append(layer)

                # Log download
                DownloadRecord.objects.create(
                    user=user,
                    layer=layer,
                    latitude=lat,
                    longitude=lng
                )

        if exported_count == 0:
            return JsonResponse({'error': 'No features found in selected area'}, status=404)

        # Deduct connects only for successfully exported layers
        if hasattr(user, 'connects') and successful_layers:
            user.connects -= len(successful_layers)
            user.save()

        # Return DXF
        response = HttpResponse(content_type='application/dxf')
        response['Content-Disposition'] = 'attachment; filename="export.dxf"'
        doc.write(response)

        logger.info(f"Exported {exported_count} features from {len(successful_layers)} layers for {user.username}")
        return response

    except Exception as e:
        logger.error(f"Export error: {e}")
        return JsonResponse({'error': 'Export failed. Please try again.'}, status=500)


def fetch_layer_features(layer, minx, miny, maxx, maxy):
    """
    Fetch features from ArcGIS REST service.
    Returns list of GEOS geometries.

    Enhanced to handle different layer types and offset coordinates.
    """
    if not layer.server:
        return []

    # For point layers with offset coordinates, check if the offset point is within bounds
    if (layer.type == 'point' and
            layer.offsetX is not None and layer.offsetY is not None and
            layer.offsetX != 0 and layer.offsetY != 0):

        # Check if offset point is within query bounds
        if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
            # Return the offset point as a feature
            try:
                point = Point(layer.offsetX, layer.offsetY, srid=4326)
                return [point]
            except:
                pass

    # Build query URL for REST service
    base_url = layer.server.url.rstrip('/')
    url = f"{base_url}/{layer.number}/query"

    # Adjust query parameters based on layer type
    spatial_rel = 'esriSpatialRelIntersects'
    if layer.type == 'point':
        # For points, use contains to get points within the envelope
        spatial_rel = 'esriSpatialRelContains'

    params = {
        'f': 'geojson',
        'where': '1=1',
        'geometry': f"{minx},{miny},{maxx},{maxy}",
        'geometryType': 'esriGeometryEnvelope',
        'spatialRel': spatial_rel,
        'inSR': 4326,
        'outSR': 4326,
        'returnGeometry': 'true',
        'outFields': '*',  # Get all fields
        'maxRecordCount': 2000  # Increased limit
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        # Check for errors in response
        if 'error' in data:
            logger.error(f"ArcGIS error for {layer.name}: {data['error']}")
            return []

        features = data.get('features', [])

        # If no features but layer has offset coordinates, return offset point
        if not features and layer.type == 'point' and layer.offsetX and layer.offsetY:
            if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
                try:
                    point = Point(layer.offsetX, layer.offsetY, srid=4326)
                    return [point]
                except:
                    pass

        geometries = []
        for feature in features:
            geom_data = feature.get('geometry')
            if geom_data:
                try:
                    # Convert to GEOS geometry
                    geom = GEOSGeometry(json.dumps(geom_data))
                    if geom.valid:
                        geometries.append(geom)
                except:
                    continue

        logger.debug(f"Fetched {len(geometries)} features for {layer.name}")
        return geometries

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching features for {layer.name}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error for {layer.name}: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to fetch features for {layer.name}: {e}")
        return []


def draw_geometry_to_dxf(msp, geom, layer_name):
    """
    Draw a GEOS geometry to DXF modelspace.
    Simplified drawing logic.
    """
    attrs = {'layer': layer_name}

    try:
        geom_type = geom.geom_type

        if geom_type == 'Point':
            msp.add_point((geom.x, geom.y), dxfattribs=attrs)

        elif geom_type == 'LineString':
            coords = list(geom.coords)
            if len(coords) >= 2:
                msp.add_lwpolyline(coords, dxfattribs=attrs)

        elif geom_type == 'Polygon':
            # Draw exterior ring
            coords = list(geom.exterior.coords)
            if len(coords) >= 3:
                msp.add_lwpolyline(coords, close=True, dxfattribs=attrs)

            # Draw holes
            for interior in geom.interiors:
                coords = list(interior.coords)
                if len(coords) >= 3:
                    msp.add_lwpolyline(coords, close=True, dxfattribs=attrs)

        elif geom_type == 'MultiPoint':
            for point in geom:
                msp.add_point((point.x, point.y), dxfattribs=attrs)

        elif geom_type == 'MultiLineString':
            for line in geom:
                coords = list(line.coords)
                if len(coords) >= 2:
                    msp.add_lwpolyline(coords, dxfattribs=attrs)

        elif geom_type == 'MultiPolygon':
            for poly in geom:
                draw_geometry_to_dxf(msp, poly, layer_name)

    except Exception as e:
        logger.error(f"Error drawing {geom_type}: {e}")


# Optional: Additional utility endpoints

@login_required
def layer_info(request, layer_id):
    """
    Get detailed information about a specific layer.
    Useful for tooltips and popups.
    """
    try:
        layer = get_object_or_404(Layer, layer_id=layer_id)

        data = {
            'id': layer.layer_id,
            'name': layer.name,
            'type': layer.type,
            'server': {
                'name': layer.server.name if layer.server else 'Unknown',
                'url': layer.server.url if layer.server else None
            },
            'symbol': layer.symbol,
            'has_geometry': bool(layer.geometry),
            'extent': layer.geometry.extent if layer.geometry else None
        }

        return JsonResponse(data)

    except Exception as e:
        logger.error(f"Error getting layer info: {e}")
        return JsonResponse({'error': 'Failed to get layer info'}, status=500)


@login_required
def check_connects(request):
    """
    Check user's available connects.
    """
    connects = getattr(request.user, 'connects', 0)
    return JsonResponse({
        'connects': connects,
        'username': request.user.username
    })