import json

from django.core.serializers import serialize
from django.http import JsonResponse, HttpResponse
from django.shortcuts import render

# Create your views here.
from rest_framework import generics
from .models import Server, Layer
from .serializers import ServerSerializer, LayerSerializer


# def index(request):
#     return render(request, 'index.html')

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


def download_layer(request, layer_id):
    try:
        # Fetch the layer by ID
        layer = Layer.objects.get(pk=layer_id)

        # Export layer geometry as GeoJSON
        geojson_data = serialize(
            'geojson',
            [layer],
            geometry_field='geometry',
            fields=('name', 'type', 'number', 'symbol')  # Add relevant fields here
        )

        # Send GeoJSON as an attachment
        response = HttpResponse(geojson_data, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="layer_{layer_id}.geojson"'
        return response
    except Layer.DoesNotExist:
        return JsonResponse({"error": "Layer not found"}, status=404)