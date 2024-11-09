import json

from django.core.serializers import serialize
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
