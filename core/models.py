# core/models.py
from django.db import models
from django.contrib.gis.db import models as gis_models
from django.conf import settings


class Server(models.Model):
    """GIS Server configuration for ArcGIS REST services"""

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
    """GIS Layer from an ArcGIS REST service"""

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
    """Track user downloads for analytics and billing"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='downloads'
    )
    layer = models.ForeignKey(
        Layer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    zoom = models.IntegerField(null=True, blank=True)
    downloaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.layer.name if self.layer else 'N/A'} - {self.downloaded_at}"

    class Meta:
        ordering = ['-downloaded_at']


class UserLayerPreference(models.Model):
    """
    Stores user's preferred/frequently used layers.
    Layers are automatically saved when downloaded.
    On next login, these layers are pre-selected.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='layer_preferences'
    )
    layer = models.ForeignKey(
        Layer,
        on_delete=models.CASCADE,
        related_name='user_preferences'
    )
    download_count = models.PositiveIntegerField(default=1)
    last_used = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_favorite = models.BooleanField(default=False)

    class Meta:
        unique_together = ['user', 'layer']
        ordering = ['-download_count', '-last_used']

    def __str__(self):
        return f"{self.user.username} - {self.layer.name} ({self.download_count}x)"

    @classmethod
    def update_preference(cls, user, layer):
        """Update or create preference, incrementing download count."""
        preference, created = cls.objects.get_or_create(
            user=user,
            layer=layer,
            defaults={'download_count': 1}
        )
        if not created:
            preference.download_count += 1
            preference.save(update_fields=['download_count', 'last_used'])
        return preference

    @classmethod
    def get_preferred_layer_ids(cls, user, limit=50):
        """Get list of preferred layer IDs for a user."""
        return list(
            cls.objects.filter(user=user)
            .order_by('-download_count', '-last_used')
            .values_list('layer_id', flat=True)[:limit]
        )

    @classmethod
    def toggle_favorite(cls, user, layer_id):
        """Toggle favorite status for a layer."""
        try:
            layer = Layer.objects.get(layer_id=layer_id)
            preference, created = cls.objects.get_or_create(
                user=user,
                layer=layer,
                defaults={'is_favorite': True, 'download_count': 0}
            )
            if not created:
                preference.is_favorite = not preference.is_favorite
                preference.save(update_fields=['is_favorite', 'last_used'])
            return preference.is_favorite
        except Layer.DoesNotExist:
            return False