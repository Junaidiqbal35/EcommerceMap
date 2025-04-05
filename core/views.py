import ezdxf
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.serializers import serialize
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render, redirect
from django.contrib.gis.geos import Polygon
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
    layers_json = serialize('json', layers)

    return render(request, 'home.html', {'servers_json': servers_json, 'layers_json': layers_json,
                                         'user_connects': request.user.connects })


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


# @login_required
# def export_dxf(request):
#     print('export_dxf called')
#
#     user = request.user
#
#
#     try:
#         lat = float(request.GET.get('lat'))
#         lng = float(request.GET.get('lng'))
#         zoom = int(request.GET.get('zoom'))
#         min_lat = float(request.GET.get('minLat'))
#         min_lng = float(request.GET.get('minLng'))
#         max_lat = float(request.GET.get('maxLat'))
#         max_lng = float(request.GET.get('maxLng'))
#
#         bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
#         bbox.srid = 4326
#
#         doc = ezdxf.new(dxfversion="R2010")
#         msp = doc.modelspace()
#
#         layers_in_bbox = Layer.objects.filter(geometry__intersects=bbox)
#         print(f"Layers in bounding box: {layers_in_bbox}")
#
#         if not layers_in_bbox.exists():
#             messages.warning(request, "No layers found in the selected area.")
#             return redirect('home')
#
#         downloaded_layers = []
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
#             downloaded_layers.append(layer)
#
#         # Deduct connects
#         user.connects -= 1
#         user.save()
#
#         # Record the download
#         for layer in downloaded_layers:
#             DownloadRecord.objects.create(
#                 user=user,
#                 layer=layer,
#                 latitude=lat,
#                 longitude=lng,
#                 zoom=zoom,
#             )
#
#         # Prepare the DXF response
#         response = HttpResponse(content_type='application/dxf')
#         response['Content-Disposition'] = f'attachment; filename="map_{lat}_{lng}_zoom{zoom}.dxf"'
#         doc.write(response)
#
#         messages.success(request, f"Download successful! {user.connects} connects remaining.")
#         return response
#
#     except Exception as e:
#         messages.error(request, f"Error generating DXF: {str(e)}")
#         return redirect('home')

@login_required
def export_dxf(request):
    print('export_dxf called')

    user = request.user

    try:
        lat = float(request.GET.get('lat'))
        lng = float(request.GET.get('lng'))
        zoom = int(request.GET.get('zoom'))
        min_lat = float(request.GET.get('minLat'))
        min_lng = float(request.GET.get('minLng'))
        max_lat = float(request.GET.get('maxLat'))
        max_lng = float(request.GET.get('maxLng'))

        bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
        bbox.srid = 4326  # Ensure correct SRID

        # Transform bbox to match your database SRID (replace 3857 with your actual SRID)
        bbox.transform(4326)

        # Expand the selection area slightly
        buffer_size = 0.0001
        bbox = bbox.buffer(buffer_size)

        doc = ezdxf.new(dxfversion="R2010")
        msp = doc.modelspace()

        layers_in_bbox = Layer.objects.filter(geometry__intersects=bbox)
        print(f"Bounding Box: {bbox.wkt}")
        print(f"Total layers in DB: {Layer.objects.count()}")
        print(f"Layers found: {layers_in_bbox}")

        if not layers_in_bbox.exists():
            messages.warning(request, "No layers found in the selected area.")
            return redirect('home')

        downloaded_layers = []
        for layer in layers_in_bbox:
            geometry = layer.geometry
            layer_type = layer.type.lower()

            print(f"Processing layer: {layer.name}, Type: {layer.type}, Geometry: {geometry.wkt}")

            if layer_type == 'point' and geometry.geom_type == 'Point':
                msp.add_point((geometry.x, geometry.y))

            elif layer_type == 'polyline' and geometry.geom_type in ['LineString', 'MultiLineString']:
                points = [(p[0], p[1]) for p in geometry.coords]
                msp.add_lwpolyline(points)

            elif layer_type == 'polygon' and geometry.geom_type in ['Polygon', 'MultiPolygon']:
                exterior_coords = [(p[0], p[1]) for p in geometry.exterior.coords]
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


@csrf_exempt
@require_http_methods(["GET"])
def get_layer_info(request):
    try:
        min_lat = float(request.GET.get("min_lat"))
        min_lng = float(request.GET.get("min_lng"))
        max_lat = float(request.GET.get("max_lat"))
        max_lng = float(request.GET.get("max_lng"))
        bbox = Polygon.from_bbox((min_lng, min_lat, max_lng, max_lat))
        bbox.srid = 4326

        layers = Layer.objects.filter(geometry__intersects=bbox)

        data = [{"id": layer.id, "name": layer.name, "geometry": layer.geometry.geojson} for layer in layers]


        return JsonResponse(data, safe=False)

    except Exception as e:
        return JsonResponse({"error": str(e)}, status=400)
