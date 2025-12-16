# core/services/cache_service.py
"""
Layer Cache Service - Caches layer data in Redis + Database
"""

import json
import hashlib
import logging
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class CacheKeyBuilder:
    """Build consistent cache keys"""
    
    PREFIX = 'gis'
    
    @classmethod
    def layer_metadata(cls, layer_id):
        return f"{cls.PREFIX}:layer:{layer_id}:meta"
    
    @classmethod
    def layer_features(cls, layer_id, bbox_hash):
        return f"{cls.PREFIX}:layer:{layer_id}:features:{bbox_hash}"
    
    @classmethod
    def user_preferences(cls, user_id):
        return f"{cls.PREFIX}:user:{user_id}:prefs"
    
    @classmethod
    def server_health(cls, server_id):
        return f"{cls.PREFIX}:server:{server_id}:health"
    
    @classmethod
    def bbox_hash(cls, minx, miny, maxx, maxy):
        """Create hash for bounding box"""
        bbox_str = f"{minx:.6f},{miny:.6f},{maxx:.6f},{maxy:.6f}"
        return hashlib.md5(bbox_str.encode()).hexdigest()[:12]


class LayerCacheService:
    """
    Two-tier caching: Redis (fast) + Database (persistent)
    """
    
    REDIS_TTL = 3600  # 1 hour
    DB_TTL_HOURS = 24  # 24 hours
    
    def get_layer_metadata(self, layer_id):
        """
        Get layer metadata from cache.
        Checks Redis first, then database.
        """
        cache_key = CacheKeyBuilder.layer_metadata(layer_id)
        
        # Try Redis first
        data = cache.get(cache_key)
        if data:
            logger.debug(f"Cache HIT (Redis): {cache_key}")
            return data
        
        # Try database cache
        try:
            from core.models import LayerCache
            layer_cache = LayerCache.objects.get(layer_id=layer_id)
            
            if layer_cache.is_valid():
                data = layer_cache.metadata_json
                # Promote to Redis
                cache.set(cache_key, data, self.REDIS_TTL)
                logger.debug(f"Cache HIT (DB): {cache_key}")
                return data
        except LayerCache.DoesNotExist:
            pass
        
        logger.debug(f"Cache MISS: {cache_key}")
        return None
    
    def set_layer_metadata(self, layer_id, metadata):
        """
        Store layer metadata in both Redis and database.
        """
        cache_key = CacheKeyBuilder.layer_metadata(layer_id)
        
        # Store in Redis
        cache.set(cache_key, metadata, self.REDIS_TTL)
        
        # Store in database
        try:
            from core.models import LayerCache, Layer
            layer = Layer.objects.get(pk=layer_id)
            
            LayerCache.objects.update_or_create(
                layer=layer,
                defaults={
                    'metadata_json': metadata,
                    'expires_at': timezone.now() + timedelta(hours=self.DB_TTL_HOURS)
                }
            )
        except Layer.DoesNotExist:
            logger.warning(f"Layer {layer_id} not found for caching")
        except Exception as e:
            logger.error(f"Error caching layer metadata: {e}")
    
    def get_cached_features(self, layer_id, bbox):
        """Get cached features for a bounding box"""
        bbox_hash = CacheKeyBuilder.bbox_hash(*bbox)
        cache_key = CacheKeyBuilder.layer_features(layer_id, bbox_hash)
        
        data = cache.get(cache_key)
        if data:
            logger.debug(f"Features cache HIT: {cache_key}")
            return data
        
        return None
    
    def set_cached_features(self, layer_id, bbox, features, ttl=1800):
        """Cache features for a bounding box (30 min default)"""
        bbox_hash = CacheKeyBuilder.bbox_hash(*bbox)
        cache_key = CacheKeyBuilder.layer_features(layer_id, bbox_hash)
        
        cache.set(cache_key, features, ttl)
        logger.debug(f"Cached {len(features)} features: {cache_key}")
    
    def invalidate_layer(self, layer_id):
        """Invalidate all cache for a layer"""
        cache_key = CacheKeyBuilder.layer_metadata(layer_id)
        cache.delete(cache_key)
        
        try:
            from core.models import LayerCache
            LayerCache.objects.filter(layer_id=layer_id).delete()
        except Exception as e:
            logger.error(f"Error invalidating layer cache: {e}")
    
    def invalidate_user_preferences(self, user_id):
        """Invalidate user preference cache"""
        cache_key = CacheKeyBuilder.user_preferences(user_id)
        cache.delete(cache_key)
    
    def get_user_preferences(self, user_id):
        """Get cached user preferences"""
        cache_key = CacheKeyBuilder.user_preferences(user_id)
        return cache.get(cache_key)
    
    def set_user_preferences(self, user_id, preferences, ttl=300):
        """Cache user preferences (5 min)"""
        cache_key = CacheKeyBuilder.user_preferences(user_id)
        cache.set(cache_key, preferences, ttl)
    
    def get_server_health(self, server_id):
        """Get cached server health status"""
        cache_key = CacheKeyBuilder.server_health(server_id)
        return cache.get(cache_key)
    
    def set_server_health(self, server_id, is_healthy, ttl=60):
        """Cache server health (1 min)"""
        cache_key = CacheKeyBuilder.server_health(server_id)
        cache.set(cache_key, is_healthy, ttl)
    
    def cleanup_expired(self):
        """Remove expired database cache entries"""
        from core.models import LayerCache
        deleted, _ = LayerCache.cleanup_expired()
        logger.info(f"Cleaned up {deleted} expired cache entries")
        return deleted


# Global instance
layer_cache_service = LayerCacheService()