from django.db import models
from django.contrib.gis.db import models as gis_models
from accounts.models import User
from django.utils import timezone


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
    """
    Track user's layer preferences and download history
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    layer = models.ForeignKey('Layer', on_delete=models.CASCADE)
    
    # Preference tracking
    is_favorite = models.BooleanField(default=False)
    download_count = models.IntegerField(default=0)
    last_downloaded = models.DateTimeField(null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        unique_together = ['user', 'layer']
        indexes = [
            models.Index(fields=['user', '-download_count']),
            models.Index(fields=['user', '-last_downloaded']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.layer.name}"
    
    def increment_download(self):
        """Increment download counter and update timestamp"""
        self.download_count += 1
        self.last_downloaded = timezone.now()
        self.save(update_fields=['download_count', 'last_downloaded', 'updated_at'])
    
    def mark_favorite(self):
        """Mark layer as favorite"""
        self.is_favorite = True
        self.save(update_fields=['is_favorite', 'updated_at'])
    
    def unmark_favorite(self):
        """Remove favorite status"""
        self.is_favorite = False
        self.save(update_fields=['is_favorite', 'updated_at'])
    
    @classmethod
    def get_or_create_preference(cls, user, layer):
        """Get or create preference for user-layer combination"""
        preference, created = cls.objects.get_or_create(
            user=user,
            layer=layer
        )
        return preference
    
    @classmethod
    def get_user_favorites(cls, user):
        """Get all favorite layers for a user"""
        return cls.objects.filter(
            user=user,
            is_favorite=True
        ).select_related('layer')
    
    @classmethod
    def get_frequently_downloaded(cls, user, limit=10):
        """Get user's most downloaded layers"""
        return cls.objects.filter(
            user=user,
            download_count__gt=0
        ).order_by('-download_count')[:limit].select_related('layer')  
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