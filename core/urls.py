# urls.py - Complete URL configuration

from django.urls import path
from . import views
from core.views import (
    user_downloads,
    toggle_favorite,
    hide_from_downloads,
    download_stats,
)

urlpatterns = [
    # Main page
    path('', views.home, name='home'),

    # Layer management
    path('layer-list/', views.layer_list, name='layer_list'),
    path('layer-preview-features/', views.layer_preview_features, name='layer_preview_features'),
    path('layer-preview-status/', views.layer_status_check, name='layer_status_check'),

    # User interaction
    path('nearby-layers/', views.nearby_layers, name='nearby_layers'),
    # path('user-connects/', views.user_connects, name='user_connects'),

    # Export/Download
    path('export-dxf-multi/', views.export_dxf_multi, name='export_dxf_multi'),
    path('download-layers/', views.download_layers, name='download_layers'),

    # Utility
    path('check-connects/', views.check_connects, name='check_connects'),

    path('downloads/', user_downloads, name='user_downloads'),
    path('api/layers/<int:layer_id>/favorite/', toggle_favorite, name='toggle_favorite'),
    path('api/layers/<int:layer_id>/hide/', hide_from_downloads, name='hide_from_downloads'),
    path('api/user/stats/', download_stats, name='download_stats'),

]