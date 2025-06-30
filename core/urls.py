from django.urls import path
from . import views

urlpatterns = [
    # Main pages
    path("", views.home, name="home"),

    # Server and layer endpoints (NEW - fixes clustering issue)
    path("server-coverage/", views.server_coverage, name="server_coverage"),
    path("all-layers/", views.all_layers, name="all_layers"),

    # Layer preview endpoint (NEW - enables layer preview on map)
    path("layer-preview-features/", views.layer_preview_features, name="layer_preview_features"),

    # Existing layer endpoints
    path("map-layers/", views.map_layers, name="map_layers"),
    path("marker-layers/", views.marker_layers, name="marker_layers"),
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),

    # Export functionality
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),

    # Utility endpoints (NEW - for admin and user info)
    path("layer-status-summary/", views.layer_status_summary, name="layer_status_summary"),
    path("user-connects-info/", views.user_connects_info, name="user_connects_info"),
]