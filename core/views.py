import json
import math
import requests
import ezdxf
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.contrib.gis.geos import Point, GEOSGeometry
from django.contrib.gis.db.models.functions import Distance
from django.db.models import Q

from .models import Layer, DownloadRecord, UserLayerPreference

import logging

logger = logging.getLogger(__name__)

# ~1km envelope for queries
OFFSET_DEG = 0.01
# Limit preview features
MAX_FEATURES_PREVIEW = 500


def is_htmx_request(request):
    """Check if request is from HTMX"""
    return request.headers.get('HX-Request') == 'true'


@login_required
def home(request):
    """Render the main map page"""
    return render(request, "home.html")


@login_required
def all_layers(request):
    """
    Return all layers with basic information.
    Returns HTML for HTMX, JSON for API calls.
    """
    search = request.GET.get('search', '').strip()
    
    layers = Layer.objects.select_related('server').all().order_by('server__name', 'name')
    
    # Apply search filter
    if search:
        layers = layers.filter(
            Q(name__icontains=search) | 
            Q(server__name__icontains=search) |
            Q(type__icontains=search)
        )
    
    # Get user's preferred layer IDs
    preferred_ids = UserLayerPreference.get_user_preferred_layers(request.user, limit=20)
    favorite_ids = UserLayerPreference.get_user_favorites(request.user)
    
    # Build layer data
    data = []
    for layer in layers:
        centroid_lat = centroid_lng = None
        if layer.geometry:
            try:
                centroid = layer.geometry.centroid
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
            'is_preferred': layer.layer_id in preferred_ids,
            'is_favorite': layer.layer_id in favorite_ids
        })
    
    # Return HTML for HTMX requests
    if is_htmx_request(request):
        # Group by server
        grouped = {}
        for layer in data:
            server = layer['server_name']
            if server not in grouped:
                grouped[server] = []
            grouped[server].append(layer)
        
        return render(request, 'partials/layer_list.html', {
            'grouped_layers': grouped,
            'selected_ids': []
        })
    
    # Return JSON for API calls
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
        if area > 0.5:
            return JsonResponse({
                'type': 'FeatureCollection',
                'features': [],
                'message': 'Area too large. Please zoom in.'
            })

        features = fetch_layer_features(layer, minx, miny, maxx, maxy)

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
@csrf_exempt
def nearby_layers(request):
    """
    Return layers near a point with distance information.
    Returns HTML for HTMX POST, JSON for GET API calls.
    """
    # Handle both GET and POST
    if request.method == 'POST':
        lat = request.POST.get('lat')
        lng = request.POST.get('lng')
        dist = request.POST.get('dist', 2000)
    else:
        lat = request.GET.get('lat')
        lng = request.GET.get('lng')
        dist = request.GET.get('dist', 2000)
    
    try:
        lat = float(lat)
        lng = float(lng)
        dist = float(dist)
    except (TypeError, ValueError):
        if is_htmx_request(request):
            return render(request, 'partials/nearby_layers.html', {'layers': []})
        return JsonResponse([], safe=False)

    point = Point(lng, lat, srid=4326)

    # Find layers with geometry within distance
    layers_with_geom = Layer.objects.annotate(
        distance=Distance('geometry', point)
    ).filter(
        distance__lte=dist,
        geometry__isnull=False
    ).select_related('server')

    # Also check offset-based layers
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

    # Combine and deduplicate
    all_layers = list(layers_with_geom) + list(layers_with_offset)
    seen = set()
    unique_layers = []
    for layer in all_layers:
        if layer.layer_id not in seen:
            seen.add(layer.layer_id)
            unique_layers.append(layer)

    data = []
    for layer in unique_layers[:30]:
        try:
            if hasattr(layer, 'distance') and layer.distance:
                distance_m = round(layer.distance.m, 1)
                if layer.geometry:
                    centroid = layer.geometry.centroid
                    layer_lat, layer_lng = centroid.y, centroid.x
                else:
                    layer_lat, layer_lng = layer.offsetY, layer.offsetX
            else:
                if layer.offsetX and layer.offsetY:
                    layer_lat, layer_lng = layer.offsetY, layer.offsetX
                    dx = (lng - layer_lng) * 111000 * math.cos(math.radians(lat))
                    dy = (lat - layer_lat) * 111000
                    distance_m = round(math.sqrt(dx * dx + dy * dy), 1)
                else:
                    continue

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
    data = data[:20]

    # Return HTML for HTMX requests
    if is_htmx_request(request):
        return render(request, 'partials/nearby_layers.html', {'layers': data})
    
    return JsonResponse(data, safe=False)


@login_required
@csrf_exempt
@require_POST
def export_dxf_multi(request):
    """
    Export selected layers as DXF file.
    """
    user = request.user
    layer_ids = request.POST.getlist('layer_ids[]')
    minx = request.POST.get('minx')
    miny = request.POST.get('miny')
    maxx = request.POST.get('maxx')
    maxy = request.POST.get('maxy')

    lat = request.POST.get('lat')
    lng = request.POST.get('lng')

    if not layer_ids:
        return JsonResponse({'error': 'No layers selected'}, status=400)

    try:
        minx, miny = float(minx), float(miny)
        maxx, maxy = float(maxx), float(maxy)

        if lat and lng:
            lat, lng = float(lat), float(lng)
        else:
            lat = (miny + maxy) / 2
            lng = (minx + maxx) / 2

        area = (maxx - minx) * (maxy - miny)
        if area > 1.0:
            return JsonResponse({
                'error': 'Area too large. Please zoom in to a smaller area.'
            }, status=400)

        layers = Layer.objects.filter(layer_id__in=layer_ids).select_related('server')

        if not layers.exists():
            return JsonResponse({'error': 'No valid layers found'}, status=404)

        # Check user connects
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
            features = fetch_layer_features(layer, minx, miny, maxx, maxy)

            layer_feature_count = 0
            for geom in features:
                if geom and geom.valid:
                    draw_geometry_to_dxf(msp, geom, layer.name)
                    layer_feature_count += 1
                    exported_count += 1

            if layer_feature_count > 0:
                successful_layers.append(layer)

                DownloadRecord.objects.create(
                    user=user,
                    layer=layer,
                    latitude=lat,
                    longitude=lng
                )
                
                # Update user preferences
                UserLayerPreference.update_preference(user, layer)

        if exported_count == 0:
            return JsonResponse({'error': 'No features found in selected area'}, status=404)

        # Deduct connects
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


# ============ USER PREFERENCES ENDPOINTS ============

@login_required
@require_GET
def get_user_preferences(request):
    """Get user's layer preferences"""
    preferred_ids = UserLayerPreference.get_user_preferred_layers(request.user, limit=20)
    favorite_ids = UserLayerPreference.get_user_favorites(request.user)
    
    preferences = UserLayerPreference.objects.filter(
        user=request.user
    ).select_related('layer', 'layer__server')[:20]
    
    pref_data = []
    for pref in preferences:
        pref_data.append({
            'layer_id': pref.layer_id,
            'layer_name': pref.layer.name,
            'server_name': pref.layer.server.name if pref.layer.server else 'Unknown',
            'download_count': pref.download_count,
            'is_favorite': pref.is_favorite,
            'last_used': pref.last_used.isoformat()
        })
    
    return JsonResponse({
        'preferred_layer_ids': preferred_ids,
        'favorite_layer_ids': favorite_ids,
        'preferences': pref_data
    })


@login_required
@require_POST
@csrf_exempt
def toggle_favorite_layer(request):
    """Toggle favorite status for a layer"""
    try:
        data = json.loads(request.body)
        layer_id = data.get('layer_id')
        
        if not layer_id:
            return JsonResponse({'error': 'layer_id required'}, status=400)
        
        layer = get_object_or_404(Layer, layer_id=layer_id)
        
        pref, created = UserLayerPreference.objects.get_or_create(
            user=request.user,
            layer=layer,
            defaults={'download_count': 0}
        )
        
        pref.is_favorite = not pref.is_favorite
        pref.save()
        
        return JsonResponse({
            'success': True,
            'is_favorite': pref.is_favorite,
            'layer_id': layer_id
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Toggle favorite error: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
@csrf_exempt
def save_layer_selection(request):
    """Manually save layer selections as preferences"""
    try:
        data = json.loads(request.body)
        layer_ids = data.get('layer_ids', [])
        
        for layer_id in layer_ids:
            try:
                layer = Layer.objects.get(layer_id=layer_id)
                UserLayerPreference.update_preference(request.user, layer)
            except Layer.DoesNotExist:
                continue
        
        return JsonResponse({'success': True, 'saved': len(layer_ids)})
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)


@login_required
@require_POST
@csrf_exempt
def clear_preferences(request):
    """Clear all user preferences"""
    deleted_count = UserLayerPreference.objects.filter(user=request.user).delete()[0]
    return JsonResponse({'success': True, 'deleted': deleted_count})


# ============ HELPER FUNCTIONS ============

def fetch_layer_features(layer, minx, miny, maxx, maxy):
    """Fetch features from ArcGIS REST service."""
    if not layer.server:
        return []

    # Check offset point layers
    if (layer.type == 'point' and
            layer.offsetX is not None and layer.offsetY is not None and
            layer.offsetX != 0 and layer.offsetY != 0):
        if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
            try:
                point = Point(layer.offsetX, layer.offsetY, srid=4326)
                return [point]
            except:
                pass

    # Build query URL
    base_url = layer.server.url.rstrip('/')
    url = f"{base_url}/{layer.number}/query"

    spatial_rel = 'esriSpatialRelIntersects'
    if layer.type == 'point':
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
        'outFields': '*',
        'maxRecordCount': 2000
    }

    try:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if 'error' in data:
            logger.error(f"ArcGIS error for {layer.name}: {data['error']}")
            return []

        features = data.get('features', [])

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
                    geom = GEOSGeometry(json.dumps(geom_data))
                    if geom.valid:
                        geometries.append(geom)
                except:
                    continue

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
    """Draw a GEOS geometry to DXF modelspace."""
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
            coords = list(geom.exterior.coords)
            if len(coords) >= 3:
                msp.add_lwpolyline(coords, close=True, dxfattribs=attrs)
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