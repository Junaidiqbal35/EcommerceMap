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
    status = models.CharField(max_length=20, default='active')
    last_validated = models.DateTimeField(null=True, blank=True)
    error_count = models.IntegerField(default=0)
    last_error = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


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
    status = models.CharField(max_length=20, default='active')
    last_validated = models.DateTimeField(null=True, blank=True)
    feature_count = models.IntegerField(null=True, blank=True)
    last_error = models.TextField(blank=True, null=True)

    # Geometry field for spatial queries
    geometry = gis_models.GeometryField(srid=4326, null=True, blank=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['server__name', 'name']

    def get_extent(self):

        if self.geometry:
            try:
                return self.geometry.extent
            except:
                pass
        return None


class DownloadRecord(models.Model):

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='downloads')
    layer = models.ForeignKey(Layer, on_delete=models.SET_NULL, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    zoom = models.IntegerField(null=True, blank=True)
    downloaded_at = models.DateTimeField(auto_now_add=True)
    feature_count = models.IntegerField(null=True, blank=True)
    file_format = models.CharField(max_length=10, default='dxf')
    bbox_min_x = models.FloatField(null=True, blank=True)
    bbox_min_y = models.FloatField(null=True, blank=True)
    bbox_max_x = models.FloatField(null=True, blank=True)
    bbox_max_y = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} - {self.layer.name if self.layer else 'N/A'} - {self.downloaded_at}"

    class Meta:
        ordering = ['-downloaded_at']

class UserLayerPreference(models.Model):
    """Track user preferences for layers"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='layer_preferences')
    layer = models.ForeignKey(Layer, on_delete=models.CASCADE, related_name='user_preferences')
    download_count = models.IntegerField(default=0)
    last_downloaded = models.DateTimeField(null=True, blank=True)
    first_downloaded = models.DateTimeField(auto_now_add=True)
    is_favorite = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    custom_name = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        unique_together = ('user', 'layer')

class LayerCache(models.Model):
    """Cache layer metadata"""
    layer = models.OneToOneField(Layer, on_delete=models.CASCADE, related_name='cache')
    metadata_json = models.JSONField(null=True, blank=True)
    fields_json = models.JSONField(null=True, blank=True)
    sample_features_json = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()

class LayerValidationLog(models.Model):
    """Audit log for validations"""
    layer = models.ForeignKey(Layer, on_delete=models.CASCADE, related_name='validation_logs')
    validated_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20)
    message = models.TextField(blank=True, null=True)
    response_time_ms = models.IntegerField(null=True, blank=True)
    triggered_by = models.CharField(max_length=50, default='manual')