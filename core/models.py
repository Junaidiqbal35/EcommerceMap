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

    class Meta:
        ordering = ['name']


class Layer(models.Model):
    LAYER_TYPES = [
        ('point', 'Point'),
        ('polyline', 'Polyline'),
        ('polygon', 'Polygon'),
    ]

    # NEW: Status choices for layer availability monitoring
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('intermittent', 'Intermittent'),
        ('inactive', 'Inactive'),
        ('unknown', 'Unknown')
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

    # NEW: Layer status monitoring fields
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='unknown',
        help_text='Current availability status of this layer'
    )
    last_checked = models.DateTimeField(
        null=True, blank=True,
        help_text='When this layer was last checked for availability'
    )
    last_successful_access = models.DateTimeField(
        null=True, blank=True,
        help_text='When this layer last responded successfully'
    )
    error_count = models.IntegerField(
        default=0,
        help_text='Number of consecutive errors encountered'
    )
    error_message = models.TextField(
        blank=True,
        help_text='Details of the last error encountered'
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['server__name', 'name']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['last_checked']),
            models.Index(fields=['server', 'type']),
        ]

    @property
    def status_display(self):
        """Return a user-friendly status with emoji"""
        status_map = {
            'active': '✅ Active',
            'intermittent': '⚠️ Intermittent',
            'inactive': '❌ Inactive',
            'unknown': '❓ Unknown'
        }
        return status_map.get(self.status, '❓ Unknown')

    def is_available(self):
        """Check if layer is available for download"""
        return self.status in ['active', 'intermittent']


class DownloadRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='downloads')
    layer = models.ForeignKey(Layer, on_delete=models.SET_NULL, null=True, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    zoom = models.IntegerField(null=True, blank=True)
    downloaded_at = models.DateTimeField(auto_now_add=True)

    # NEW: Track which coordinate system was used for download
    srid = models.IntegerField(
        null=True, blank=True,
        help_text='Spatial Reference System ID used for this download'
    )

    # NEW: Track download method and area
    download_method = models.CharField(
        max_length=20,
        choices=[
            ('point', 'Point-based'),
            ('bbox', 'Bounding box'),
            ('nearby', 'Nearby layers')
        ],
        default='point',
        help_text='Method used to select download area'
    )

    feature_count = models.IntegerField(
        null=True, blank=True,
        help_text='Number of features included in this download'
    )

    def __str__(self):
        method = f" ({self.download_method})" if self.download_method != 'point' else ""
        return f"{self.user.username} - {self.layer.name if self.layer else 'N/A'} - {self.downloaded_at.strftime('%Y-%m-%d %H:%M')}{method}"

    class Meta:
        ordering = ['-downloaded_at']
        indexes = [
            models.Index(fields=['user', '-downloaded_at']),
            models.Index(fields=['layer', '-downloaded_at']),
            models.Index(fields=['downloaded_at']),
        ]


# NEW: Spatial Reference System model for coordinate system selection
class SpatialReferenceSystem(models.Model):
    srid = models.IntegerField(primary_key=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    region = models.CharField(max_length=100, blank=True)
    is_default = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} (EPSG:{self.srid})"

    class Meta:
        verbose_name = "Spatial Reference System"
        verbose_name_plural = "Spatial Reference Systems"
        ordering = ['region', 'name']