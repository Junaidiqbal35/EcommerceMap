import ezdxf
from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render
from django.contrib.gis.geos import Polygon
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
# Create your views here.
from rest_framework import generics
from .models import Server, Layer, DownloadRecord

from .serializers import ServerSerializer, LayerSerializer


@login_required
def index(request):
    servers = Server.objects.all()
    layers = Layer.objects.all()
    servers_json = serialize('json', servers)
    print(servers_json)
    layers_json = serialize('json', layers)
    return render(request, 'home.html', {'servers_json': servers_json, 'layers_json': layers_json})


class ServerListAPIView(generics.ListAPIView):
    queryset = Server.objects.all()
    serializer_class = ServerSerializer


class LayerListAPIView(generics.ListAPIView):
    queryset = Layer.objects.all()
    serializer_class = LayerSerializer


def get_layers(request):
    bbox = request.GET.get('bbox')
    if bbox:
        min_x, min_y, max_x, max_y = map(float, bbox.split(','))

        layers = Layer.objects.filter(
            server__extent_min_x__lte=max_x, server__extent_max_x__gte=min_x,
            server__extent_min_y__lte=max_y, server__extent_max_y__gte=min_y
        )

        print(layers)

        layers_data = [
            {
                "id": layer.layer_id,
                "name": layer.name,
                "server": {
                    "url": layer.server.url
                },
                "number": layer.number,
                "type": layer.type
            }
            for layer in layers
        ]
        return JsonResponse(layers_data, safe=False)

    return JsonResponse({"error": "Bounding box not provided"}, status=400)


# def export_layer_to_dxf(request, layer_id):
#     try:
#         # Fetch the layer by ID
#         layer = Layer.objects.get(layer_id=layer_id)
#
#         # Initialize DXF document
#         doc = ezdxf.new(dxfversion="R2010")
#         msp = doc.modelspace()  # Access the model space
#
#         # Check the layer type and process geometry
#         if layer.geometry:
#             geometry = GEOSGeometry(layer.geometry)
#
#             if layer.type == 'point' and geometry.geom_type == 'Point':
#                 # Add a DXF point
#                 msp.add_point((geometry.x, geometry.y))
#
#             elif layer.type == 'polyline' and geometry.geom_type == 'LineString':
#                 # Add a DXF polyline
#                 points = [(p[0], p[1]) for p in geometry.coords]
#                 msp.add_lwpolyline(points)
#
#             elif layer.type == 'polygon' and geometry.geom_type == 'Polygon':
#                 # Add a DXF polygon (closed polyline)
#                 exterior_coords = [(p[0], p[1]) for p in geometry.coords[0]]
#                 msp.add_lwpolyline(exterior_coords, close=True)
#
#         # Prepare the response for downloading the DXF file
#         response = HttpResponse(content_type='application/dxf')
#         response['Content-Disposition'] = f'attachment; filename="{layer.name}.dxf"'
#
#         # Save the DXF content to the response
#         doc.write(response)
#         return response
#
#     except Layer.DoesNotExist:
#         return HttpResponse("Layer not found.", status=404)
#     except Exception as e:
#         return HttpResponse(f"Error exporting layer: {str(e)}", status=500)

# def export_dxf(request):
#     try:
#         # Get latitude, longitude, zoom, and bounds from the request
#         lat = float(request.GET.get('lat'))
#         lng = float(request.GET.get('lng'))
#         zoom = int(request.GET.get('zoom'))
#         min_lat = float(request.GET.get('minLat'))
#         min_lng = float(request.GET.get('minLng'))
#         max_lat = float(request.GET.get('maxLat'))
#         max_lng = float(request.GET.get('maxLng'))
#
#         # Create a bounding box geometry from the given bounds
#         bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
#
#         # Initialize DXF document
#         doc = ezdxf.new(dxfversion="R2010")
#         msp = doc.modelspace()  # Access the model space
#
#         # Query layers within the bounding box
#         layers_in_bbox = Layer.objects.filter(geometry__intersects=bbox)
#
#         for layer in layers_in_bbox:
#             geometry = layer.geometry
#
#             if layer.type == 'point' and geometry.geom_type == 'Point':
#                 msp.add_point((geometry.x, geometry.y))
#
#             elif layer.type == 'polyline' and geometry.geom_type == 'LineString':
#                 points = [(p[0], p[1]) for p in geometry.coords]
#                 msp.add_lwpolyline(points)
#
#             elif layer.type == 'polygon' and geometry.geom_type == 'Polygon':
#                 exterior_coords = [(p[0], p[1]) for p in geometry.coords[0]]
#                 msp.add_lwpolyline(exterior_coords, close=True)
#
#         # Prepare the DXF response
#         response = HttpResponse(content_type='application/dxf')
#         response['Content-Disposition'] = f'attachment; filename="map_{lat}_{lng}_zoom{zoom}.dxf"'
#         doc.write(response)
#         return response
#
#     except Exception as e:
#         return HttpResponse(f"Error generating DXF: {str(e)}", status=500)


@login_required
def export_dxf(request):
    try:
        # Get latitude, longitude, zoom, and bounds from the request
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        zoom = int(request.GET.get('zoom'))
        min_lat = float(request.GET.get('minLat'))
        min_lng = float(request.GET.get('minLng'))
        max_lat = float(request.GET.get('maxLat'))
        max_lng = float(request.GET.get('maxLng'))

        # Create a bounding box geometry from the given bounds
        bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))

        # Initialize DXF document
        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()  # Access the model space

        # Query layers within the bounding box
        layers_in_bbox = Layer.objects.filter(geometry__intersects=bbox)

        downloaded_layers = []  # Keep track of downloaded layers for record
        for layer in layers_in_bbox:
            geometry = layer.geometry

            if layer.type == 'point' and geometry.geom_type == 'Point':
                msp.add_point((geometry.x, geometry.y))

            elif layer.type == 'polyline' and geometry.geom_type == 'LineString':
                points = [(p[0], p[1]) for p in geometry.coords]
                msp.add_lwpolyline(points)

            elif layer.type == 'polygon' and geometry.geom_type == 'Polygon':
                exterior_coords = [(p[0], p[1]) for p in geometry.coords[0]]
                msp.add_lwpolyline(exterior_coords, close=True)

            downloaded_layers.append(layer)

        # Prepare the DXF response
        response = HttpResponse(content_type='application/dxf')
        response['Content-Disposition'] = f'attachment; filename="map_{lat}_{lng}_zoom{zoom}.dxf"'
        doc.write(response)

        # Record the download
        for layer in downloaded_layers:
            DownloadRecord.objects.create(
                user=request.user,
                layer=layer,
                latitude=lat,
                longitude=lng,
                zoom=zoom,
            )

        return response

    except Exception as e:
        return HttpResponse(f"Error generating DXF: {str(e)}", status=500)


# layer info
@csrf_exempt
@require_http_methods(["GET"])
def get_layer_info(request):
    try:
        # Get latitude and longitude from query parameters
        lat = float(request.GET.get('lat', None))
        lng = float(request.GET.get('lng', None))

        if lat is None or lng is None:
            return JsonResponse({"error": "Latitude and longitude are required."}, status=400)

        # Create a Point object for the query location
        user_location = Point(lng, lat, srid=4326)

        # Find the closest layer to the provided location within a reasonable distance (e.g., 500 meters)
        layer = (
            Layer.objects.annotate(distance=Distance('geometry', user_location))
            .filter(geometry__isnull=False)
            .order_by('distance')
            .first()
        )

        if layer and layer.distance.m <= 500:
            data = {
                "name": layer.name,
                "type": layer.type,
                "distance": round(layer.distance.m, 2),
                "details": {
                    "offsetX": layer.offsetX,
                    "offsetY": layer.offsetY,
                    "symbol": layer.symbol,
                    "insert": layer.insert,
                },
            }
        else:
            # Default message when no layer is found within the range
            data = {"info": "No nearby layers found for the given location."}

        return JsonResponse(data)

    except ValueError:
        return JsonResponse({"error": "Invalid latitude or longitude format."}, status=400)
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)
