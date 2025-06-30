# Add these demo data functions to your views.py

import random

import ezdxf
from django.contrib.auth.decorators import login_required
from django.contrib.gis.geos import Point, LineString, Polygon
from django.dispatch.dispatcher import logger
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST




def home(request):
    return render(request, 'demo_home.html')


@login_required
def demo_server_coverage(request):
    """Demo server data for testing"""
    demo_servers = [
        {
            'id': 1,
            'name': 'Brisbane City Demo',
            'lat': -27.4698,
            'lng': 153.0251,
            'layer_count': 12,
            'extent': {
                'min_x': 152.9, 'min_y': -27.6,
                'max_x': 153.2, 'max_y': -27.3
            }
        },
        {
            'id': 2,
            'name': 'Perth City Demo',
            'lat': -31.9505,
            'lng': 115.8605,
            'layer_count': 8,
            'extent': {
                'min_x': 115.7, 'min_y': -32.1,
                'max_x': 116.0, 'max_y': -31.8
            }
        },
        {
            'id': 3,
            'name': 'Sydney CBD Demo',
            'lat': -33.8688,
            'lng': 151.2093,
            'layer_count': 15,
            'extent': {
                'min_x': 151.1, 'min_y': -33.9,
                'max_x': 151.3, 'max_y': -33.8
            }
        }
    ]
    return JsonResponse(demo_servers, safe=False)


@login_required
def demo_all_layers(request):
    """Demo layers for testing"""
    demo_layers = [
        # Brisbane layers
        {'id': 1, 'name': 'Brisbane Water Mains', 'type': 'polyline', 'number': 1,
         'server_url': 'demo', 'server_name': 'Brisbane City Demo', 'status': 'active'},
        {'id': 2, 'name': 'Brisbane Sewer Lines', 'type': 'polyline', 'number': 2,
         'server_url': 'demo', 'server_name': 'Brisbane City Demo', 'status': 'active'},
        {'id': 3, 'name': 'Brisbane Manholes', 'type': 'point', 'number': 3,
         'server_url': 'demo', 'server_name': 'Brisbane City Demo', 'status': 'active'},
        {'id': 4, 'name': 'Brisbane Property Boundaries', 'type': 'polygon', 'number': 4,
         'server_url': 'demo', 'server_name': 'Brisbane City Demo', 'status': 'active'},

        # Perth layers
        {'id': 5, 'name': 'Perth Water Network', 'type': 'polyline', 'number': 5,
         'server_url': 'demo', 'server_name': 'Perth City Demo', 'status': 'active'},
        {'id': 6, 'name': 'Perth Electrical Cables', 'type': 'polyline', 'number': 6,
         'server_url': 'demo', 'server_name': 'Perth City Demo', 'status': 'intermittent'},
        {'id': 7, 'name': 'Perth Utility Poles', 'type': 'point', 'number': 7,
         'server_url': 'demo', 'server_name': 'Perth City Demo', 'status': 'active'},

        # Sydney layers
        {'id': 8, 'name': 'Sydney Stormwater Drains', 'type': 'polyline', 'number': 8,
         'server_url': 'demo', 'server_name': 'Sydney CBD Demo', 'status': 'active'},
        {'id': 9, 'name': 'Sydney Building Footprints', 'type': 'polygon', 'number': 9,
         'server_url': 'demo', 'server_name': 'Sydney CBD Demo', 'status': 'active'},
        {'id': 10, 'name': 'Sydney Traffic Lights', 'type': 'point', 'number': 10,
         'server_url': 'demo', 'server_name': 'Sydney CBD Demo', 'status': 'active'},

        # Some inactive layers for testing
        {'id': 11, 'name': 'Old Gas Lines', 'type': 'polyline', 'number': 11,
         'server_url': 'demo', 'server_name': 'Brisbane City Demo', 'status': 'inactive'},
        {'id': 12, 'name': 'Legacy Telecom', 'type': 'point', 'number': 12,
         'server_url': 'demo', 'server_name': 'Perth City Demo', 'status': 'inactive'},
    ]

    return JsonResponse(demo_layers, safe=False)


@login_required
def demo_layer_preview_features(request):
    """Generate demo GeoJSON features for testing"""
    layer_id = request.GET.get('layer_id')
    minx = float(request.GET.get('minx', 0))
    miny = float(request.GET.get('miny', 0))
    maxx = float(request.GET.get('maxx', 0))
    maxy = float(request.GET.get('maxy', 0))

    # Get layer info
    layer_map = {
        '1': {'name': 'Brisbane Water Mains', 'type': 'polyline'},
        '2': {'name': 'Brisbane Sewer Lines', 'type': 'polyline'},
        '3': {'name': 'Brisbane Manholes', 'type': 'point'},
        '4': {'name': 'Brisbane Property Boundaries', 'type': 'polygon'},
        '5': {'name': 'Perth Water Network', 'type': 'polyline'},
        '6': {'name': 'Perth Electrical Cables', 'type': 'polyline'},
        '7': {'name': 'Perth Utility Poles', 'type': 'point'},
        '8': {'name': 'Sydney Stormwater Drains', 'type': 'polyline'},
        '9': {'name': 'Sydney Building Footprints', 'type': 'polygon'},
        '10': {'name': 'Sydney Traffic Lights', 'type': 'point'},
    }

    layer_info = layer_map.get(layer_id)
    if not layer_info:
        return JsonResponse({'type': 'FeatureCollection', 'features': []})

    features = []
    feature_count = random.randint(5, 20)

    for i in range(feature_count):
        # Generate random coordinates within bounds
        lng = minx + (maxx - minx) * random.random()
        lat = miny + (maxy - miny) * random.random()

        if layer_info['type'] == 'point':
            geometry = {
                'type': 'Point',
                'coordinates': [lng, lat]
            }
        elif layer_info['type'] == 'polyline':
            # Generate a random line
            coords = []
            for j in range(random.randint(2, 5)):
                offset_lng = lng + (random.random() - 0.5) * 0.01
                offset_lat = lat + (random.random() - 0.5) * 0.01
                coords.append([offset_lng, offset_lat])
            geometry = {
                'type': 'LineString',
                'coordinates': coords
            }
        else:  # polygon
            # Generate a random rectangle
            width = random.uniform(0.001, 0.005)
            height = random.uniform(0.001, 0.005)
            coords = [[
                [lng, lat],
                [lng + width, lat],
                [lng + width, lat + height],
                [lng, lat + height],
                [lng, lat]
            ]]
            geometry = {
                'type': 'Polygon',
                'coordinates': coords
            }

        feature = {
            'type': 'Feature',
            'geometry': geometry,
            'properties': {
                'layer_name': layer_info['name'],
                'layer_type': layer_info['type'],
                'layer_id': layer_id,
                'demo_id': f"demo_{layer_id}_{i}"
            }
        }
        features.append(feature)

    return JsonResponse({
        'type': 'FeatureCollection',
        'features': features,
        'total_features': len(features),
        'demo_data': True
    })


@login_required
def demo_nearby_layers(request):
    """Demo nearby layers based on location"""
    lat = float(request.GET.get('lat', 0))
    lng = float(request.GET.get('lng', 0))

    # Determine which demo region we're in
    if -27.6 <= lat <= -27.3 and 152.9 <= lng <= 153.2:
        # Brisbane area
        layers = [
            {'id': 1, 'name': 'Brisbane Water Mains', 'type': 'polyline', 'status': 'active', 'distance_m': 150},
            {'id': 2, 'name': 'Brisbane Sewer Lines', 'type': 'polyline', 'status': 'active', 'distance_m': 200},
            {'id': 3, 'name': 'Brisbane Manholes', 'type': 'point', 'status': 'active', 'distance_m': 300},
            {'id': 4, 'name': 'Brisbane Property Boundaries', 'type': 'polygon', 'status': 'active', 'distance_m': 50},
        ]
    elif -32.1 <= lat <= -31.8 and 115.7 <= lng <= 116.0:
        # Perth area
        layers = [
            {'id': 5, 'name': 'Perth Water Network', 'type': 'polyline', 'status': 'active', 'distance_m': 100},
            {'id': 6, 'name': 'Perth Electrical Cables', 'type': 'polyline', 'status': 'intermittent',
             'distance_m': 250},
            {'id': 7, 'name': 'Perth Utility Poles', 'type': 'point', 'status': 'active', 'distance_m': 180},
        ]
    elif -33.9 <= lat <= -33.8 and 151.1 <= lng <= 151.3:
        # Sydney area
        layers = [
            {'id': 8, 'name': 'Sydney Stormwater Drains', 'type': 'polyline', 'status': 'active', 'distance_m': 120},
            {'id': 9, 'name': 'Sydney Building Footprints', 'type': 'polygon', 'status': 'active', 'distance_m': 80},
            {'id': 10, 'name': 'Sydney Traffic Lights', 'type': 'point', 'status': 'active', 'distance_m': 220},
        ]
    else:
        layers = []

    return JsonResponse(layers, safe=False)


@login_required
@csrf_exempt
@require_POST
def demo_export_dxf_multi(request):
    """Demo DXF export that generates sample DXF with demo data"""
    user = request.user
    layer_ids = request.POST.getlist('layer_ids[]')
    lat = request.POST.get('lat')
    lng = request.POST.get('lng')
    srid = request.POST.get('srid', '28356')

    if not layer_ids:
        return JsonResponse({'error': 'No layers selected.'}, status=400)

    # Check connects (if user has connects system)
    needed = len(layer_ids)
    if hasattr(user, 'connects'):
        if user.connects < needed:
            return JsonResponse({'error': f'Not enough connects. Need {needed}, you have {user.connects}.'}, status=403)
        user.connects -= needed
        user.save()

    try:
        # Create demo DXF with sample data
        doc = ezdxf.new('R2010')
        msp = doc.modelspace()

        # Generate demo geometries for each selected layer
        for layer_id in layer_ids:
            layer_name = f"Demo_Layer_{layer_id}"

            if layer_id in ['1', '2', '5', '6', '8']:  # Line layers
                # Create sample lines
                for i in range(5):
                    start_x = float(lng) + random.uniform(-0.01, 0.01) if lng else random.uniform(150, 155)
                    start_y = float(lat) + random.uniform(-0.01, 0.01) if lat else random.uniform(-35, -25)
                    points = [(start_x, start_y), (start_x + 0.005, start_y + 0.002)]
                    msp.add_lwpolyline(points, dxfattribs={'layer': layer_name})

            elif layer_id in ['3', '7', '10']:  # Point layers
                # Create sample points
                for i in range(8):
                    x = float(lng) + random.uniform(-0.01, 0.01) if lng else random.uniform(150, 155)
                    y = float(lat) + random.uniform(-0.01, 0.01) if lat else random.uniform(-35, -25)
                    msp.add_point((x, y), dxfattribs={'layer': layer_name})

            elif layer_id in ['4', '9']:  # Polygon layers
                # Create sample rectangles
                for i in range(3):
                    x = float(lng) + random.uniform(-0.01, 0.01) if lng else random.uniform(150, 155)
                    y = float(lat) + random.uniform(-0.01, 0.01) if lat else random.uniform(-35, -25)
                    points = [(x, y), (x + 0.002, y), (x + 0.002, y + 0.002), (x, y + 0.002), (x, y)]
                    msp.add_lwpolyline(points, close=True, dxfattribs={'layer': layer_name})

        # Return DXF file
        response = HttpResponse(content_type='application/dxf')
        response['Content-Disposition'] = 'attachment; filename="demo_export.dxf"'
        doc.write(response)
        return response

    except Exception as e:
        logger.error(f"Demo DXF export error: {e}")
        return JsonResponse({'error': 'Demo export failed'}, status=500)
