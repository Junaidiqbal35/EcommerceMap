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

    layer_id = models.IntegerField(primary_key=True)
    server = models.ForeignKey(Server, related_name='layers', on_delete=models.CASCADE)
    type = models.CharField(max_length=10, choices=LAYER_TYPES)
    number = models.IntegerField()
    name = models.CharField(max_length=255)
    offsetX = models.FloatField(default=0)
    offsetY = models.FloatField(default=0)
    symbol = models.CharField(max_length=255, blank=True, null=True)
    insert = models.CharField(max_length=255, blank=True, null=True)

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

    def __str__(self):
        return f"{self.user.username} - {self.layer.name if self.layer else 'N/A'} - {self.downloaded_at}"

    class Meta:
        ordering = ['-downloaded_at']


class UserLayerPreference(models.Model):
    """
    Stores user's preferred layers for quick access.
    Automatically updated when user downloads layers.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='layer_preferences')
    layer = models.ForeignKey(Layer, on_delete=models.CASCADE, related_name='user_preferences')
    download_count = models.IntegerField(default=1)
    last_used = models.DateTimeField(auto_now=True)
    is_favorite = models.BooleanField(default=False)  # User can manually favorite
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['user', 'layer']
        ordering = ['-download_count', '-last_used']
        verbose_name = 'User Layer Preference'
        verbose_name_plural = 'User Layer Preferences'

    def __str__(self):
        return f"{self.user.username} - {self.layer.name} ({self.download_count}x)"

    @classmethod
    def update_preference(cls, user, layer):
        """
        Update or create preference when user downloads a layer.
        Increments download count and updates last_used.
        """
        pref, created = cls.objects.get_or_create(
            user=user,
            layer=layer,
            defaults={'download_count': 1}
        )
        if not created:
            pref.download_count += 1
            pref.save(update_fields=['download_count', 'last_used'])
        return pref

    @classmethod
    def get_user_preferred_layers(cls, user, limit=20):
        """
        Get user's most frequently used layers.
        Returns layer IDs ordered by usage frequency.
        """
        return list(
            cls.objects.filter(user=user)
            .order_by('-download_count', '-last_used')[:limit]
            .values_list('layer_id', flat=True)
        )

    @classmethod
    def get_user_favorites(cls, user):
        """Get layers marked as favorites."""
        return list(
            cls.objects.filter(user=user, is_favorite=True)
            .values_list('layer_id', flat=True)
        )