import logging
import requests
import ezdxf
import json
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Point, Polygon
from django.db.models import Q, Count
from .models import Layer, DownloadRecord, Server

from django.utils import timezone
# Configure logger
logger = logging.getLogger(__name__)

# HTTP session with retries for REST calls
session = requests.Session()
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retries = Retry(total=3, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(max_retries=retries)
session.mount('http://', adapter)
session.mount('https://', adapter)
session.headers.update({'User-Agent': 'GIS-Export-Agent/1.0'})

# Query envelope offset (in degrees) - ~1km
OFFSET_DEG = 0.01


@login_required
def home(request):
    """Renders main map page"""
    return render(request, "home.html")


@login_required
def server_coverage(request):
    """
    Return server coverage areas instead of individual layer markers.
    This fixes the clustering issue by showing one marker per server coverage area.
    """
    servers = Server.objects.exclude(
        Q(extent_min_x__isnull=True) |
        Q(extent_min_y__isnull=True) |
        Q(extent_max_x__isnull=True) |
        Q(extent_max_y__isnull=True)
    ).annotate(layer_count=Count('layers'))

    data = []
    for server in servers:
        if server.layer_count > 0:
            # Calculate center of server coverage area
            center_x = (server.extent_min_x + server.extent_max_x) / 2
            center_y = (server.extent_min_y + server.extent_max_y) / 2

            # Validate coordinates are reasonable
            if -180 <= center_x <= 180 and -90 <= center_y <= 90:
                data.append({
                    'id': server.id,
                    'name': server.name,
                    'lat': center_y,
                    'lng': center_x,
                    'layer_count': server.layer_count,
                    'extent': {
                        'min_x': server.extent_min_x,
                        'min_y': server.extent_min_y,
                        'max_x': server.extent_max_x,
                        'max_y': server.extent_max_y
                    }
                })

    return JsonResponse(data, safe=False)


@login_required
def all_layers(request):
    """
    Return all available layers for the layer control panel.
    Organized by server with status information.
    """
    layers = Layer.objects.select_related('server').all().order_by('server__name', 'name')

    data = []
    for layer in layers:
        # Get geometry for layer positioning if available
        geom = getattr(layer, 'geometry', None)
        centroid_lat = centroid_lng = None

        if geom and geom.valid:
            try:
                centroid = geom.centroid
                centroid_lat = centroid.y
                centroid_lng = centroid.x
            except Exception:
                pass

        data.append({
            'id': layer.layer_id,
            'name': layer.name,
            'type': layer.type,
            'number': layer.number,
            'server_url': layer.server.url if layer.server else '',
            'server_name': layer.server.name if layer.server else 'Unknown Server',
            'status': getattr(layer, 'status', 'unknown'),
            'last_checked': getattr(layer, 'last_checked', None),
            'centroid_lat': centroid_lat,
            'centroid_lng': centroid_lng,
            'error_message': getattr(layer, 'error_message', '')
        })

    return JsonResponse(data, safe=False)


@login_required
def layer_preview_features(request):
    """
    Get preview features for a layer in the current map view.
    This replaces WMS with actual vector features.
    """
    layer_id = request.GET.get('layer_id')
    minx = request.GET.get('minx')
    miny = request.GET.get('miny')
    maxx = request.GET.get('maxx')
    maxy = request.GET.get('maxy')

    if not all([layer_id, minx, miny, maxx, maxy]):
        return JsonResponse({'error': 'Missing parameters'}, status=400)

    try:
        layer = Layer.objects.select_related('server').get(layer_id=layer_id)
        minx, miny, maxx, maxy = float(minx), float(miny), float(maxx), float(maxy)

        # Limit preview area to prevent huge downloads
        area = (maxx - minx) * (maxy - miny)
        if area > 0.1:  # About 10km x 10km at equator
            return JsonResponse({
                'type': 'FeatureCollection',
                'features': [],
                'message': 'Area too large for preview. Zoom in for details.'
            })

        # Fetch features for preview (limited number)
        geoms = fetch_layer_features_bbox(layer, minx, miny, maxx, maxy)

        # Convert to GeoJSON (limit to first 200 features for performance)
        features = []
        for geom in geoms[:200]:
            if geom and geom.valid:
                try:
                    feature = {
                        'type': 'Feature',
                        'geometry': json.loads(geom.geojson),
                        'properties': {
                            'layer_name': layer.name,
                            'layer_type': layer.type,
                            'layer_id': layer.layer_id
                        }
                    }
                    features.append(feature)
                except Exception as e:
                    logger.debug(f"Error converting geometry to GeoJSON: {e}")
                    continue

        return JsonResponse({
            'type': 'FeatureCollection',
            'features': features,
            'total_features': len(geoms),
            'preview_limit': 200 if len(geoms) > 200 else None
        })

    except Layer.DoesNotExist:
        return JsonResponse({'error': 'Layer not found'}, status=404)
    except Exception as e:
        logger.error(f"Preview error for layer {layer_id}: {e}")
        return JsonResponse({'error': 'Preview failed'}, status=500)


@login_required
def map_layers(request):
    """
    DEPRECATED: Use server_coverage instead.
    This is kept for backward compatibility.
    """
    return server_coverage(request)


@login_required
def marker_layers(request):
    """Return a single layer entry for a clicked marker."""
    marker_id = request.GET.get('marker_id')
    try:
        lid = int(marker_id)
    except (TypeError, ValueError):
        return JsonResponse([], safe=False)
    lyr = get_object_or_404(Layer, layer_id=lid)
    if not getattr(lyr, 'geometry', None) and lyr.type == 'point':
        # point with no offset
        if lyr.offsetX == 0 and lyr.offsetY == 0:
            return JsonResponse([], safe=False)
    return JsonResponse([{'id': lyr.layer_id, 'name': lyr.name, 'type': lyr.type}], safe=False)


@login_required
def nearby_layers(request):
    """
    Return layers either by bounding box (minx,miny,maxx,maxy) or by radius (lat,lng,dist)
    with optional distance_m for radius search.
    Enhanced with status information and better filtering.
    """
    qs = Layer.objects.none()

    # bbox search
    if all(k in request.GET for k in ('minx', 'miny', 'maxx', 'maxy')):
        try:
            minx, miny, maxx, maxy = [float(request.GET[k]) for k in ('minx', 'miny', 'maxx', 'maxy')]
            bbox = Polygon.from_bbox((minx, miny, maxx, maxy))
            qs = Layer.objects.filter(geometry__intersects=bbox)
        except ValueError:
            return JsonResponse([], safe=False)
    # radius search
    elif request.GET.get('lat') and request.GET.get('lng'):
        try:
            lat = float(request.GET['lat'])
            lng = float(request.GET['lng'])
            dist = float(request.GET.get('dist', 1000))  # Increased default to 1km
        except ValueError:
            return JsonResponse([], safe=False)
        pt = Point(lng, lat, srid=4326)
        qs = Layer.objects.annotate(distance=Distance('geometry', pt)).filter(distance__lte=dist).order_by('distance')
    else:
        return JsonResponse([], safe=False)

    data = []
    for lyr in qs:
        geom = getattr(lyr, 'geometry', None)
        if not geom:
            continue

        try:
            centroid = geom.centroid
            item = {
                'id': lyr.layer_id,
                'name': lyr.name,
                'type': lyr.type,
                'lat': centroid.y,
                'lng': centroid.x,
                'status': getattr(lyr, 'status', 'unknown'),
                'server_name': lyr.server.name if lyr.server else 'Unknown'
            }
            if hasattr(lyr, 'distance'):
                item['distance_m'] = round(lyr.distance.m, 1)
            data.append(item)
        except Exception as e:
            logger.debug(f"Error processing layer {lyr.layer_id}: {e}")
            continue

    return JsonResponse(data, safe=False)


@login_required
@csrf_exempt
@require_POST
def export_dxf_multi(request):
    """
    Enhanced export function with better error handling and coordinate transformation.
    Supports both point-based and bounding box exports.
    """
    user = request.user
    layer_ids = request.POST.getlist('layer_ids[]')
    lat = request.POST.get('lat')
    lng = request.POST.get('lng')
    srid = request.POST.get('srid', '28356')  # Default to GDA94 Zone 56

    # Check for bounding box parameters
    minx = request.POST.get('minx')
    miny = request.POST.get('miny')
    maxx = request.POST.get('maxx')
    maxy = request.POST.get('maxy')

    # Validate coordinates
    try:
        if lat and lng:
            lat = float(lat)
            lng = float(lng)
        else:
            lat = lng = None

        if minx and miny and maxx and maxy:
            minx, miny, maxx, maxy = float(minx), float(miny), float(maxx), float(maxy)
            # Validate bounding box area
            area = (maxx - minx) * (maxy - miny)
            if area > 1.0:  # About 100km x 100km
                return JsonResponse({'error': 'Export area too large. Please zoom in and try again.'}, status=400)
        else:
            minx = miny = maxx = maxy = None

        srid = int(srid)
    except (TypeError, ValueError) as e:
        return JsonResponse({'error': f'Invalid coordinate parameters: {str(e)}'}, status=400)

    if not layer_ids:
        return JsonResponse({'error': 'No layers selected.'}, status=400)

    candidates = Layer.objects.filter(layer_id__in=layer_ids)
    if not candidates.exists():
        return JsonResponse({'error': 'No valid layers found.'}, status=404)

    # Check user connects
    needed = len(candidates)
    if hasattr(user, 'connects'):
        if user.connects < needed:
            return JsonResponse({
                'error': f'Not enough connects. Need {needed}, you have {user.connects}. Please purchase more connects.'
            }, status=403)

    # Fetch features for each layer
    exports = []
    skipped_layers = []

    for lyr in candidates:
        rest_geoms = []
        try:
            if minx is not None:
                # Bounding box export
                rest_geoms = fetch_layer_features_bbox(lyr, minx, miny, maxx, maxy)
            else:
                # Point-based export
                rest_geoms = fetch_layer_features(lyr, lat, lng)
        except Exception as e:
            logger.warning(f"REST fetch error for {lyr.name}: {e}")
            skipped_layers.append(lyr.name)
            continue

        if lyr.type in ('polyline', 'polygon'):
            if not rest_geoms:
                logger.warning(f"Skipping {lyr.name}: no REST features for {lyr.type}")
                skipped_layers.append(lyr.name)
                continue
            exports.append((lyr, rest_geoms))
        else:  # point layer
            if rest_geoms:
                exports.append((lyr, rest_geoms))
            elif lyr.geometry:
                exports.append((lyr, [lyr.geometry]))
            else:
                skipped_layers.append(lyr.name)

    if not exports:
        error_msg = 'No geometry to export for selected area.'
        if skipped_layers:
            error_msg += f' Skipped layers: {", ".join(skipped_layers)}'
        return JsonResponse({'error': error_msg}, status=400)

    # Deduct connects only for successful exports
    actual_cost = len(exports)
    if hasattr(user, 'connects'):
        user.connects -= actual_cost
        user.save()

    # Create DXF with coordinate transformation
    try:
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()

        total_features = 0
        for lyr, geoms in exports:
            layer_feature_count = 0
            for g in geoms:
                if not g or not g.valid:
                    continue

                # Transform geometry to target SRID
                if g.srid != srid:
                    try:
                        g = g.transform(srid, clone=True)
                    except Exception as e:
                        logger.warning(f"Transform error {g.srid}->{srid} for {lyr.name}: {e}")
                        continue

                # Draw geometry in DXF
                draw_geometry(msp, g, lyr.name)
                layer_feature_count += 1
                total_features += 1

            # Record download for layers that had features
            if layer_feature_count > 0:
                DownloadRecord.objects.create(
                    user=user,
                    layer=lyr,
                    latitude=lat,
                    longitude=lng
                    # Add SRID to model if you have this field
                    # srid=srid
                )

        # Return DXF file
        response = HttpResponse(content_type='application/dxf')
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'gis_export_{timestamp}.dxf'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        doc.write(response)

        logger.info(f"Exported {total_features} features from {len(exports)} layers for user {user.username}")
        return response

    except Exception as e:
        logger.error(f"DXF creation error: {e}")
        return JsonResponse({'error': 'Failed to create DXF file. Please try again.'}, status=500)


def fetch_layer_features(layer, lat, lng):
    """
    Query ArcGIS REST for features in a square envelope around click point.
    Returns list of GEOS geometries.
    """
    if lat is None or lng is None:
        return []
    minx, miny = lng - OFFSET_DEG, lat - OFFSET_DEG
    maxx, maxy = lng + OFFSET_DEG, lat + OFFSET_DEG
    return fetch_layer_features_bbox(layer, minx, miny, maxx, maxy)


def fetch_layer_features_bbox(layer, minx, miny, maxx, maxy):
    """
    Enhanced feature fetching with better error handling and optimization.
    Returns list of GEOS geometries.
    """
    if not layer.server:
        logger.warning(f"Layer {layer.name} has no server configured")
        return []

    # Build query URL
    base_url = layer.server.url.rstrip('/')
    url = f"{base_url}/{layer.number}/query"

    params = {
        'f': 'geojson',
        'where': '1=1',
        'geometry': f"{minx},{miny},{maxx},{maxy}",
        'geometryType': 'esriGeometryEnvelope',
        'inSR': 4326,
        'outSR': 4326,
        'returnGeometry': 'true',
        'maxRecordCount': 2000,  # Limit to prevent huge downloads
        'resultOffset': 0
    }

    try:
        logger.debug(f"Fetching features for {layer.name} from {url}")
        resp = session.get(url, params=params, timeout=20)
        resp.raise_for_status()

        gj = resp.json()

        # Check for ArcGIS error response
        if 'error' in gj:
            error_msg = gj['error'].get('message', 'Unknown error')
            logger.error(f"ArcGIS error for {layer.name}: {error_msg}")
            return []

        geoms = []
        features = gj.get('features', [])

        for feat in features:
            geom = geojson_to_geos(feat.get('geometry'))
            if geom and geom.valid:
                geoms.append(geom)

        logger.debug(f"Fetched {len(geoms)} valid features for {layer.name}")
        return geoms

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching features for {layer.name}")
        return []
    except requests.exceptions.RequestException as e:
        logger.error(f"Request error for {layer.name}: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error fetching {layer.name}: {e}")
        return []


def geojson_to_geos(coords):
    """
    Enhanced GeoJSON to GEOS conversion with better error handling.
    """
    try:
        from django.contrib.gis.geos import GEOSGeometry

        if not coords or not coords.get('type') or not coords.get('coordinates'):
            return None

        # Validate coordinate structure
        geom_type = coords.get('type')
        coordinates = coords.get('coordinates')

        if geom_type == 'Point' and len(coordinates) < 2:
            return None
        elif geom_type == 'LineString' and len(coordinates) < 2:
            return None
        elif geom_type == 'Polygon' and not coordinates:
            return None

        gj = {
            'type': geom_type,
            'coordinates': coordinates
        }

        geom = GEOSGeometry(json.dumps(gj), srid=4326)

        # Validate geometry
        if not geom.valid:
            logger.debug(f"Invalid geometry created from GeoJSON: {geom_type}")
            return None

        return geom

    except Exception as e:
        logger.debug(f"GeoJSON conversion error: {e}")
        return None


def draw_geometry(msp, geom, layer_name):
    """
    Enhanced geometry drawing with better error handling and layer organization.
    """
    if not geom or not geom.valid:
        return

    t = geom.geom_type

    # Create DXF attributes with layer name
    dxf_attrs = {'layer': layer_name}

    try:
        if t == 'Point':
            msp.add_point((geom.x, geom.y), dxfattribs=dxf_attrs)
        elif t in ('LineString', 'LinearRing'):
            coords = list(geom.coords)
            if len(coords) >= 2:
                msp.add_lwpolyline(coords, dxfattribs=dxf_attrs)
        elif t == 'MultiLineString':
            for ln in geom:
                coords = list(ln.coords)
                if len(coords) >= 2:
                    msp.add_lwpolyline(coords, dxfattribs=dxf_attrs)
        elif t == 'Polygon':
            # Exterior ring
            exterior_coords = list(geom.exterior.coords)
            if len(exterior_coords) >= 3:
                msp.add_lwpolyline(exterior_coords, close=True, dxfattribs=dxf_attrs)
            # Interior rings (holes)
            for hole in geom.interiors:
                hole_coords = list(hole.coords)
                if len(hole_coords) >= 3:
                    msp.add_lwpolyline(hole_coords, close=True, dxfattribs=dxf_attrs)
        elif t == 'MultiPolygon':
            for poly in geom:
                draw_geometry(msp, poly, layer_name)
        elif t == 'GeometryCollection':
            for g in geom:
                draw_geometry(msp, g, layer_name)
        else:
            logger.warning(f"Unsupported geometry type: {t}")
    except Exception as e:
        logger.error(f"Error drawing {t} geometry for layer {layer_name}: {e}")


# Additional utility functions for layer management

@login_required
def layer_status_summary(request):
    """Get a summary of layer statuses for admin dashboard"""
    from django.db.models import Count

    try:
        status_counts = Layer.objects.values('status').annotate(count=Count('status'))
        total_layers = Layer.objects.count()

        summary = {
            'total': total_layers,
            'by_status': {item['status'] or 'unknown': item['count'] for item in status_counts},
            'servers': Server.objects.count(),
            'never_checked': Layer.objects.filter(last_checked__isnull=True).count()
        }

        return JsonResponse(summary)
    except Exception as e:
        logger.error(f"Error getting layer status summary: {e}")
        return JsonResponse({'error': 'Failed to get status summary'}, status=500)


@login_required
def user_connects_info(request):
    """Get user's current connects balance"""
    try:
        connects = getattr(request.user, 'connects', 0)
        return JsonResponse({
            'connects': connects,
            'username': request.user.username
        })
    except Exception as e:
        logger.error(f"Error getting user connects info: {e}")
        return JsonResponse({'error': 'Failed to get connects info'}, status=500)


