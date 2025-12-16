# core/services/preference_service.py
"""
User Preference Service - Tracks user layer preferences and downloads
"""

from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class UserPreferenceService:
    """
    Service for managing user layer preferences.
    Auto-tracks downloads and provides recommendations.
    """
    
    def __init__(self, user):
        self.user = user
    
    def get_preferred_layers(self, limit=20):
        """
        Get user's preferred layers ordered by download count.
        """
        from core.models import UserLayerPreference
        
        preferences = UserLayerPreference.objects.filter(
            user=self.user,
            is_hidden=False,
            layer__status='active'
        ).select_related(
            'layer', 'layer__server'
        ).order_by('-download_count', '-last_downloaded')[:limit]
        
        return preferences
    
    def get_favorite_layers(self):
        """Get user's favorite layers"""
        from core.models import UserLayerPreference
        
        return UserLayerPreference.objects.filter(
            user=self.user,
            is_favorite=True,
            is_hidden=False,
            layer__status='active'
        ).select_related('layer', 'layer__server')
    
    def get_recent_downloads(self, days=7, limit=10):
        """Get recently downloaded layers"""
        from core.models import DownloadRecord
        
        cutoff = timezone.now() - timedelta(days=days)
        
        return DownloadRecord.objects.filter(
            user=self.user,
            downloaded_at__gte=cutoff,
            layer__isnull=False
        ).select_related(
            'layer', 'layer__server'
        ).order_by('-downloaded_at')[:limit]
    
    def record_download(self, layer, latitude=None, longitude=None, zoom=None,
                        feature_count=None, file_format='dxf', bbox=None):
        """
        Record a download and update preferences.
        """
        from core.models import DownloadRecord, UserLayerPreference
        
        # Create download record
        download = DownloadRecord.objects.create(
            user=self.user,
            layer=layer,
            latitude=latitude,
            longitude=longitude,
            zoom=zoom,
            feature_count=feature_count,
            file_format=file_format,
            bbox_min_x=bbox.get('min_x') if bbox else None,
            bbox_min_y=bbox.get('min_y') if bbox else None,
            bbox_max_x=bbox.get('max_x') if bbox else None,
            bbox_max_y=bbox.get('max_y') if bbox else None,
        )
        
        # Update or create preference
        pref, created = UserLayerPreference.objects.get_or_create(
            user=self.user,
            layer=layer,
            defaults={'download_count': 0}
        )
        pref.increment_download()
        
        logger.info(f"Recorded download: {self.user.username} - {layer.name}")
        
        return download
    
    def toggle_favorite(self, layer):
        """Toggle favorite status for a layer"""
        from core.models import UserLayerPreference
        
        pref, created = UserLayerPreference.objects.get_or_create(
            user=self.user,
            layer=layer
        )
        pref.is_favorite = not pref.is_favorite
        pref.save(update_fields=['is_favorite'])
        
        return pref.is_favorite
    
    def hide_layer(self, layer):
        """Hide a layer from user's download history"""
        from core.models import UserLayerPreference
        
        pref, created = UserLayerPreference.objects.get_or_create(
            user=self.user,
            layer=layer
        )
        pref.is_hidden = True
        pref.save(update_fields=['is_hidden'])
    
    def set_custom_name(self, layer, custom_name):
        """Set a custom name for a layer"""
        from core.models import UserLayerPreference
        
        pref, created = UserLayerPreference.objects.get_or_create(
            user=self.user,
            layer=layer
        )
        pref.custom_name = custom_name
        pref.save(update_fields=['custom_name'])
    
    def get_usage_stats(self):
        """Get user's download statistics"""
        from core.models import DownloadRecord, UserLayerPreference
        
        total_downloads = DownloadRecord.objects.filter(user=self.user).count()
        
        week_ago = timezone.now() - timedelta(days=7)
        recent_downloads = DownloadRecord.objects.filter(
            user=self.user,
            downloaded_at__gte=week_ago
        ).count()
        
        unique_layers = UserLayerPreference.objects.filter(
            user=self.user,
            is_hidden=False
        ).count()
        
        favorites = UserLayerPreference.objects.filter(
            user=self.user,
            is_favorite=True
        ).count()
        
        # Total features downloaded
        from django.db.models import Sum
        total_features = DownloadRecord.objects.filter(
            user=self.user,
            feature_count__isnull=False
        ).aggregate(
            total=Sum('feature_count')
        )['total'] or 0
        
        return {
            'total_downloads': total_downloads,
            'recent_downloads': recent_downloads,
            'unique_layers': unique_layers,
            'favorites': favorites,
            'total_features': total_features,
        }
    
    def get_layer_suggestions(self, current_layer=None, limit=5):
        """
        Get layer suggestions based on user's patterns.
        """
        from core.models import DownloadRecord, Layer
        
        if current_layer:
            # Find layers commonly downloaded with this one
            # Users who downloaded this also downloaded...
            other_users = DownloadRecord.objects.filter(
                layer=current_layer
            ).values_list('user_id', flat=True).distinct()
            
            common_layers = DownloadRecord.objects.filter(
                user_id__in=other_users
            ).exclude(
                layer=current_layer
            ).values('layer').annotate(
                count=Count('id')
            ).order_by('-count')[:limit]
            
            layer_ids = [l['layer'] for l in common_layers]
            return Layer.objects.filter(layer_id__in=layer_ids, status='active')
        
        # Otherwise return popular layers user hasn't downloaded
        user_layers = DownloadRecord.objects.filter(
            user=self.user
        ).values_list('layer_id', flat=True)
        
        popular = DownloadRecord.objects.exclude(
            layer_id__in=user_layers
        ).values('layer').annotate(
            count=Count('id')
        ).order_by('-count')[:limit]
        
        layer_ids = [l['layer'] for l in popular]
        return Layer.objects.filter(layer_id__in=layer_ids, status='active')


def get_preference_service(user):
    """Factory function to get preference service for a user"""
    return UserPreferenceService(user)