from rest_framework import serializers
from .models import Server, Layer


class ServerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Server
        fields = ['id', 'name', 'url', 'extent_min_x', 'extent_min_y', 'extent_max_x', 'extent_max_y']


class LayerSerializer(serializers.ModelSerializer):
    server = ServerSerializer()

    class Meta:
        model = Layer
        fields = ['layer_id', 'server', 'type', 'number', 'name', 'offsetX', 'offsetY', 'symbol', 'insert']
