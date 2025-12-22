from django.contrib import admin
from django.contrib.gis import admin as gis_admin
from import_export.admin import ImportExportModelAdmin
from .models import Server, Layer, DownloadRecord, UserLayerPreference
from .resources import ServerResource, LayerResource


@admin.register(Server)
class ServerAdmin(ImportExportModelAdmin):
    """Admin for GIS servers"""
    resource_class = ServerResource
    list_display = ['id', 'name', 'url', 'get_extent_display']
    search_fields = ['name', 'url']

    def get_extent_display(self, obj):
        """Display extent in readable format"""
        if all([obj.extent_min_x, obj.extent_min_y, obj.extent_max_x, obj.extent_max_y]):
            return f"({obj.extent_min_x:.2f}, {obj.extent_min_y:.2f}) to ({obj.extent_max_x:.2f}, {obj.extent_max_y:.2f})"
        return "Not defined"

    get_extent_display.short_description = "Extent"


@admin.register(Layer)
class LayerAdmin(ImportExportModelAdmin):
    """Admin for GIS layers with map preview"""
    resource_class = LayerResource
    list_display = ['layer_id', 'name', 'type', 'server', 'has_geometry']
    list_filter = ['type', 'server']
    search_fields = ['name', 'server__name']
    readonly_fields = ['layer_id']

    # Map settings for geometry preview
    default_lon = 153.02
    default_lat = -27.47
    default_zoom = 10

    def has_geometry(self, obj):
        """Check if layer has geometry"""
        return bool(obj.geometry)

    has_geometry.boolean = True
    has_geometry.short_description = "Has Geometry"


@admin.register(DownloadRecord)
class DownloadRecordAdmin(admin.ModelAdmin):
    """View download history"""
    list_display = ['user', 'layer', 'downloaded_at', 'get_location']
    list_filter = ['downloaded_at', 'user']
    search_fields = ['user__username', 'layer__name']
    date_hierarchy = 'downloaded_at'

    def get_location(self, obj):
        """Display download location"""
        if obj.latitude and obj.longitude:
            return f"{obj.latitude:.4f}, {obj.longitude:.4f}"
        return "Unknown"

    get_location.short_description = "Location"


@admin.register(UserLayerPreference)
class UserLayerPreferenceAdmin(admin.ModelAdmin):
    """View and manage user layer preferences"""
    list_display = ['user', 'layer', 'download_count', 'is_favorite', 'last_used']
    list_filter = ['is_favorite', 'last_used', 'user']
    search_fields = ['user__username', 'layer__name']
    date_hierarchy = 'last_used'
    readonly_fields = ['download_count', 'last_used', 'created_at']
    
    actions = ['mark_as_favorite', 'unmark_as_favorite']
    
    def mark_as_favorite(self, request, queryset):
        queryset.update(is_favorite=True)
        self.message_user(request, f"{queryset.count()} preferences marked as favorite.")
    mark_as_favorite.short_description = "Mark selected as favorite"
    
    def unmark_as_favorite(self, request, queryset):
        queryset.update(is_favorite=False)
        self.message_user(request, f"{queryset.count()} preferences unmarked as favorite.")
    unmark_as_favorite.short_description = "Unmark selected as favorite"