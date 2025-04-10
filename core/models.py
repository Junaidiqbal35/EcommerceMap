from django.db import models
from django.contrib.gis.db import models as gis_models
from accounts.models import User


class Server(models.Model):
    id = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=255)
    url = models.URLField()
    extent_min_x = models.FloatField(null=True, blank=True)
    extent_min_y = models.FloatField(null=True, blank=True)
    extent_max_x = models.FloatField(null=True, blank=True)
    extent_max_y = models.FloatField(null=True, blank=True)

    def __str__(self):
        return self.name


class Layer(models.Model):
    LAYER_TYPES = [
        ('point', 'Point'),
        ('polyline', 'Polyline'),
        ('polygon', 'Polygon'),
    ]

    layer_id = models.IntegerField(primary_key=True)
    server = models.ForeignKey(Server, related_name='layers', on_delete=models.CASCADE)
    type = models.CharField(max_length=10, choices=LAYER_TYPES)
    number = models.IntegerField()
    name = models.CharField(max_length=255)
    offsetX = models.FloatField(default=0)
    offsetY = models.FloatField(default=0)
    symbol = models.CharField(max_length=255, blank=True, null=True)
    insert = models.CharField(max_length=255, blank=True, null=True)

    geometry = gis_models.GeometryField(srid=4326, null=True, blank=True)

    def __str__(self):
        return self.name


class DownloadRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='downloads')
    layer = models.ForeignKey(Layer, on_delete=models.SET_NULL, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    zoom = models.IntegerField(null=True, blank=True)
    downloaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.layer.name if self.layer else 'N/A'} - {self.downloaded_at}"
