import ezdxf
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.gis.geos import Polygon
from django.contrib.gis.geos import Point
from django.contrib.gis.db.models.functions import Distance, Transform
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
# Create your views here.
from rest_framework import generics

from connects.models import ConnectTransaction
from .models import Server, Layer, DownloadRecord

from .serializers import ServerSerializer, LayerSerializer


@login_required
def index(request):
    servers = Server.objects.all()
    layers = Layer.objects.all()
    servers_json = serialize('json', servers)
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


@login_required
def export_dxf(request):
    print('export_dxf called')

    user = request.user
    print(user.connects)

    # Check if user has enough connects
    if not user.connects or user.connects < 1:
        messages.error(request, "You do not have enough connects to download. Please purchase more.")
        return redirect('buy_connects')  # Redirect to buy connects page

    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        zoom = int(request.GET.get('zoom'))
        min_lat = float(request.GET.get('minLat'))
        min_lng = float(request.GET.get('minLng'))
        max_lat = float(request.GET.get('maxLat'))
        max_lng = float(request.GET.get('maxLng'))

        bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
        bbox.srid = 4326

        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        layers_in_bbox = Layer.objects.filter(geometry__intersects=bbox)
        print(f"Layers in bounding box: {layers_in_bbox}")

        if not layers_in_bbox.exists():
            messages.warning(request, "No layers found in the selected area.")
            return redirect('map_page')  # Redirect to map page if no data available

        downloaded_layers = []
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

        # Deduct connects
        user.connects -= 1
        user.save()

        # Record the download
        for layer in downloaded_layers:
            DownloadRecord.objects.create(
                user=user,
                layer=layer,
                latitude=lat,
                longitude=lng,
                zoom=zoom,
            )

        # Prepare the DXF response
        response = HttpResponse(content_type='application/dxf')
        response['Content-Disposition'] = f'attachment; filename="map_{lat}_{lng}_zoom{zoom}.dxf"'
        doc.write(response)

        messages.success(request, f"Download successful! {user.connects} connects remaining.")
        return response

    except Exception as e:
        messages.error(request, f"Error generating DXF: {str(e)}")
        return redirect('home')


# @csrf_exempt
# @require_http_methods(["GET"])
# def get_layer_info(request):
#     try:
#         lat = float(request.GET.get('lat', None))
#         lng = float(request.GET.get('lng', None))
#
#         if lat is None or lng is None:
#             return JsonResponse({"error": "Latitude and longitude are required."}, status=400)
#
#         # Log the received latitude and longitude
#         print(f"Received lat: {lat}, lng: {lng}")
#
#         user_location = Point(lng, lat, srid=4326)
#         layer = (
#             Layer.objects.annotate(distance=Distance('geometry', user_location))
#             .filter(geometry__isnull=False)
#             .order_by('distance')
#             .first()
#         )
#
#         if layer:
#             print(f"Closest layer found: {layer.name}, Distance: {layer.distance.m} meters")
#         else:
#             print("No layers found within the threshold.")
#
#         if layer:
#             data = {
#                 "name": layer.name,
#                 "type": layer.type,
#                 "distance": round(layer.distance.m, 2),
#                 "details": {
#                     "offsetX": layer.offsetX,
#                     "offsetY": layer.offsetY,
#                     "symbol": layer.symbol,
#                     "insert": layer.insert,
#                 },
#             }
#         else:
#
#             data = {"info": "No nearby layers found for the given location."}
#
#         return JsonResponse(data)
#
#     except ValueError:
#         return JsonResponse({"error": "Invalid latitude or longitude format."}, status=400)
#     except Exception as e:
#         print(f"Error in get_layer_info: {str(e)}")
#         return JsonResponse({"error": str(e)}, status=500)
# @csrf_exempt
# @require_http_methods(["GET"])
# def get_layer_info(request):
#     lat = request.GET.get('lat')
#     lng = request.GET.get('lng')
#
#     if lat is None or lng is None:
#         return JsonResponse({"error": "Latitude and longitude are required."}, status=400)
#
#     try:
#         lat = float(lat)
#         lng = float(lng)
#     except ValueError:
#         return JsonResponse({"error": "Invalid latitude or longitude format."}, status=400)
#
#     try:
#         user_location = Point(lng, lat, srid=4326)
#
#         # Filter out layers without geometry, transform to SRID 4326 if needed
#         layer = (
#             Layer.objects.exclude(geometry__isnull=True)
#             .annotate(distance=Distance(Transform('geometry', 4326), user_location))
#             .filter(distance__lte=5000)  # Only consider layers within 500 meters
#             .order_by('distance')
#             .first()
#         )
#
#         if layer:
#             print(f"Closest layer found: {layer.name}, Distance: {layer.distance.m:.2f} meters")
#
#             data = {
#                 "name": layer.name,
#                 "type": layer.type,
#                 "distance": round(layer.distance.m, 2),
#                 "details": {
#                     "offsetX": getattr(layer, "offsetX", 0),
#                     "offsetY": getattr(layer, "offsetY", 0),
#                     "symbol": getattr(layer, "symbol", ""),
#                     "insert": getattr(layer, "insert", ""),
#                 },
#             }
#         else:
#             print("No layers found within the threshold.")
#             data = {"info": "No nearby layers found for the given location."}
#
#         return JsonResponse(data)
#
#     except Exception as e:
#         print(f"Error in get_layer_info: {str(e)}")
#         return JsonResponse({"error": str(e)}, status=500)

@csrf_exempt
@require_http_methods(["GET"])
def get_layer_info(request):
    try:
        min_lat = float(request.GET.get("min_lat"))
        min_lng = float(request.GET.get("min_lng"))
        max_lat = float(request.GET.get("max_lat"))
        max_lng = float(request.GET.get("max_lng"))

        # Create a bounding box polygon
        bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
        bbox.srid = 4326  # Ensure SRID is set to 4326

        # Filter layers within the bounding box
        layers = Layer.objects.filter(geometry__intersects=bbox)
        print(layers)

        # Return only the necessary layer data
        data = [{"id": layer.id, "name": layer.name, "geometry": layer.geometry.geojson} for layer in layers]

        return JsonResponse(data, safe=False)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
