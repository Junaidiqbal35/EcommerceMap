import json
import requests
import ezdxf
from ezdxf import colors
import math
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.gis.geos import Point, GEOSGeometry

from .models import Layer, DownloadRecord
from .gda2020_converter import GDA2020Converter

import logging

logger = logging.getLogger(__name__)

# Max download area: 0.001 degrees (~100m box)
MAX_DOWNLOAD_AREA = 0.001
# Limit preview features
MAX_FEATURES_PREVIEW = 500
# DXF Drawing constants
DECIMAL = 3  # number of decimal points to round to on levels
TEXT_HEIGHT = 0.5  # default text height
TEXT_OFFSET_X = 0.75
TEXT_OFFSET_Y = 0.75


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

        # Simple area check for preview (larger area allowed for viewing)
        area = (maxx - minx) * (maxy - miny)
        if area > 0.5:  # ~50km x 50km for preview
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
@require_POST
def export_dxf_multi(request):
    """
    Export selected layers as DXF file with advanced drawing features.
    Limited to 0.001 degree area (~100m box).
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

        # Parse optional center point
        if lat and lng:
            lat, lng = float(lat), float(lng)
        else:
            lat = (miny + maxy) / 2
            lng = (minx + maxx) / 2

        # Enforce 0.001 degree limit
        width = maxx - minx
        height = maxy - miny

        # If area is too large, limit it to 0.001 degrees around center
        if width > MAX_DOWNLOAD_AREA * 2 or height > MAX_DOWNLOAD_AREA * 2:
            # Recalculate bounds around center point
            minx = lng - MAX_DOWNLOAD_AREA
            maxx = lng + MAX_DOWNLOAD_AREA
            miny = lat - MAX_DOWNLOAD_AREA
            maxy = lat + MAX_DOWNLOAD_AREA

            logger.info(f"Download area limited to {MAX_DOWNLOAD_AREA} degrees around {lat}, {lng}")

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

        # Create DXF with advanced features
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()

        # Insert block definitions
        insert_blocks(doc)

        # Determine appropriate spatial reference using GDA2020 converter
        converter = GDA2020Converter()
        out_sr_wkid = converter.get_wkid(lat, lng, datum='gda94')

        # Fallback to default MGA Zone 56 if location is outside Australia
        if out_sr_wkid is None:
            out_sr_wkid = 28356  # Default to GDA94 MGA Zone 56
            logger.warning(f"Location {lat}, {lng} outside Australia, using default WKID 28356")

        exported_count = 0
        successful_layers = []

        for layer in layers:
            # Create layer if it doesn't exist
            if layer.name not in doc.layers:
                doc.layers.new(name=layer.name)

            # Create Text layer for labels
            if 'Text' not in doc.layers:
                doc.layers.new(name='Text')

            # Fetch features with appropriate MGA projection and attributes
            features_data = fetch_layer_features_with_attributes(layer, minx, miny, maxx, maxy, out_sr=out_sr_wkid)

            layer_feature_count = 0
            for feature_info in features_data:
                if feature_info['geometry'] and feature_info['geometry'].valid:
                    draw_feature_to_dxf(msp, feature_info['geometry'], feature_info['attributes'], layer)
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


@login_required
def nearby_layers(request):
    """
    Return layers that have actual features near the clicked point.
    This checks for real features, not just layer metadata.
    """
    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        dist = float(request.GET.get('dist', 2000))  # 2km default
    except (TypeError, ValueError):
        return JsonResponse([], safe=False)

    # Convert distance to degrees (rough approximation)
    degree_offset = dist / 111000.0  # 1 degree ≈ 111km

    # Query bounds around clicked point
    minx = lng - degree_offset
    maxx = lng + degree_offset
    miny = lat - degree_offset
    maxy = lat + degree_offset

    # Get all layers
    layers = Layer.objects.select_related('server').all()

    data = []

    for layer in layers:
        try:
            # Check if this layer has features at clicked location
            features = fetch_layer_features(layer, minx, miny, maxx, maxy, limit=5)  # Just check for existence

            if features:
                # Calculate distance to first feature
                first_feature = features[0]
                feature_lat = feature_lng = lat  # Default to clicked location

                try:
                    if first_feature.geom_type == 'Point':
                        feature_lat, feature_lng = first_feature.y, first_feature.x
                    else:
                        centroid = first_feature.centroid
                        feature_lat, feature_lng = centroid.y, centroid.x

                    # Calculate distance
                    import math
                    dx = (lng - feature_lng) * 111000 * math.cos(math.radians(lat))
                    dy = (lat - feature_lat) * 111000
                    distance_m = round(math.sqrt(dx * dx + dy * dy), 1)
                except:
                    distance_m = 0

                data.append({
                    'id': layer.layer_id,
                    'name': layer.name,
                    'type': layer.type,
                    'server_name': layer.server.name if layer.server else 'Unknown',
                    'distance_m': distance_m,
                    'feature_count': len(features)
                })
        except Exception as e:
            logger.debug(f"Error checking layer {layer.layer_id}: {e}")
            continue

    # Sort by distance
    data.sort(key=lambda x: x['distance_m'])

    return JsonResponse(data[:20], safe=False)  # Return top 20 layers with features


@login_required
def layer_feature_bounds(request):
    """
    Get the bounds of features for a layer in the current viewport.
    Used for auto-zooming to layer features.
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

        # Get features in current view
        features = fetch_layer_features(layer, minx, miny, maxx, maxy)

        if not features:
            # No features in current view, try larger area
            expand = 0.1  # Expand by 10%
            width = maxx - minx
            height = maxy - miny
            minx -= width * expand
            maxx += width * expand
            miny -= height * expand
            maxy += height * expand

            features = fetch_layer_features(layer, minx, miny, maxx, maxy)

        if features:
            # Calculate bounds of all features
            bounds_minx = bounds_miny = float('inf')
            bounds_maxx = bounds_maxy = float('-inf')

            for geom in features:
                extent = geom.extent  # (minx, miny, maxx, maxy)
                bounds_minx = min(bounds_minx, extent[0])
                bounds_miny = min(bounds_miny, extent[1])
                bounds_maxx = max(bounds_maxx, extent[2])
                bounds_maxy = max(bounds_maxy, extent[3])

            return JsonResponse({
                'bounds': {
                    'minx': bounds_minx,
                    'miny': bounds_miny,
                    'maxx': bounds_maxx,
                    'maxy': bounds_maxy
                },
                'feature_count': len(features)
            })
        else:
            # No features found, return layer centroid if available
            if layer.offsetX and layer.offsetY and layer.offsetX != 0:
                return JsonResponse({
                    'center': {
                        'lat': layer.offsetY,
                        'lng': layer.offsetX
                    },
                    'feature_count': 0
                })
            elif layer.geometry:
                centroid = layer.geometry.centroid
                return JsonResponse({
                    'center': {
                        'lat': centroid.y,
                        'lng': centroid.x
                    },
                    'feature_count': 0
                })
            else:
                return JsonResponse({'error': 'No features found'}, status=404)

    except Exception as e:
        logger.error(f"Error getting feature bounds: {e}")
        return JsonResponse({'error': 'Failed to get bounds'}, status=500)


def fetch_layer_features(layer, minx, miny, maxx, maxy, limit=2000, out_sr=4326):
    """
    Fetch features from ArcGIS REST service.
    Returns list of GEOS geometries.

    Added out_sr parameter for output spatial reference (28356 for MGA).
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

    # Use intersects for all geometry types
    spatial_rel = 'esriSpatialRelIntersects'

    params = {
        'f': 'geojson',
        'where': '1=1',
        'geometry': f"{minx},{miny},{maxx},{maxy}",
        'geometryType': 'esriGeometryEnvelope',
        'spatialRel': spatial_rel,
        'inSR': 4326,
        'outSR': out_sr,  # Use specified output spatial reference
        'returnGeometry': 'true',
        'outFields': '*',
        'maxRecordCount': limit
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

        # If no features found and layer has offset coordinates, check if offset is in bounds
        if not features and layer.type == 'point' and layer.offsetX and layer.offsetY:
            if (minx <= layer.offsetX <= maxx and miny <= layer.offsetY <= maxy):
                try:
                    point = Point(layer.offsetX, layer.offsetY, srid=4326)
                    return [point]
                except:
                    pass

        geometries = []
        for feature in features[:limit]:  # Respect limit
            geom_data = feature.get('geometry')
            if geom_data:
                try:
                    # Note: When out_sr is MGA (28356), coordinates will be in meters
                    geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
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


def fetch_layer_features_with_attributes(layer, minx, miny, maxx, maxy, limit=2000, out_sr=28356):
    """
    Fetch features from ArcGIS REST service with full attribute data.
    Returns list of dicts with geometry and attributes.

    Args:
        layer: Layer model instance
        minx, miny, maxx, maxy: Bounding box coordinates
        limit: Maximum number of features to return
        out_sr: Output spatial reference WKID (default 28356 = GDA94 MGA Zone 56)
    """
    if not layer.server:
        return []

    # Build query URL for REST service
    base_url = layer.server.url.rstrip('/')
    url = f"{base_url}/{layer.number}/query"

    # Use intersects for all geometry types
    spatial_rel = 'esriSpatialRelIntersects'

    params = {
        'f': 'geojson',
        'where': '1=1',
        'geometry': f"{minx},{miny},{maxx},{maxy}",
        'geometryType': 'esriGeometryEnvelope',
        'spatialRel': spatial_rel,
        'inSR': 4326,
        'outSR': out_sr,
        'returnGeometry': 'true',
        'outFields': '*',
        'maxRecordCount': limit
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

        feature_results = []
        for feature in features[:limit]:
            geom_data = feature.get('geometry')
            attributes = feature.get('properties', {}) or feature.get('attributes', {})

            if geom_data:
                try:
                    geom = GEOSGeometry(json.dumps(geom_data), srid=out_sr)
                    if geom.valid:
                        # Apply layer offsets if enabled
                        if layer.offsetX or layer.offsetY:
                            if geom.geom_type == 'Point':
                                geom = Point(geom.x + layer.offsetX / 1000, geom.y + layer.offsetY / 1000, srid=out_sr)
                            elif geom.geom_type == 'LineString':
                                coords = [(x + layer.offsetX / 1000, y + layer.offsetY / 1000) for x, y in geom.coords]
                                geom = GEOSGeometry(f'LINESTRING({" ".join([f"{x} {y}" for x, y in coords])})',
                                                    srid=out_sr)
                            elif geom.geom_type == 'Polygon':
                                exterior_coords = [(x + layer.offsetX / 1000, y + layer.offsetY / 1000) for x, y in
                                                   geom.exterior.coords]
                                geom = GEOSGeometry(f'POLYGON(({" ".join([f"{x} {y}" for x, y in exterior_coords])}))',
                                                    srid=out_sr)

                        feature_results.append({
                            'geometry': geom,
                            'attributes': attributes
                        })
                except Exception as e:
                    logger.debug(f"Error processing geometry: {e}")
                    continue

        return feature_results

    except Exception as e:
        logger.error(f"Failed to fetch features with attributes for {layer.name}: {e}")
        return []


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


def draw_geometry_to_dxf(msp, geom, layer):
    """
    Legacy function for simple geometry drawing without attributes.
    Kept for backward compatibility.
    """
    draw_feature_to_dxf(msp, geom, {}, layer)


@login_required
def check_connects(request):
    """Check user's available connects"""
    connects = getattr(request.user, 'connects', 0)
    return JsonResponse({
        'connects': connects,
        'username': request.user.username
    })