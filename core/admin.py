from django.contrib import admin
from import_export.admin import ImportExportModelAdmin

from core.models import Server, Layer, DownloadRecord
from core.resources import ServerResource, LayerResource


# Register your models here.
@admin.register(Server)
class ServerAdmin(ImportExportModelAdmin):
    resource_class = ServerResource
    list_display = ('id', 'name', 'url')
    search_fields = ('name', 'url')


@admin.register(Layer)
class LayerAdmin(ImportExportModelAdmin):
    resource_class = LayerResource
    list_display = ('layer_id', 'name', 'type', 'server')
    list_filter = ('type', 'server')
    search_fields = ('name', 'server__name')


@admin.register(DownloadRecord)
class DownloadRecordAdmin(admin.ModelAdmin):
    list_display = ('user', 'layer', 'latitude', 'longitude', 'zoom', 'downloaded_at')
    search_fields = ('user__username', 'layer__name')
    list_filter = ('downloaded_at',)
