# core/urls.py
from django.urls import path
from . import views

urlpatterns = [
    # Main map page
    path("", views.home, name="home"),

    # Layer list (HTMX partial)
    path("layer-list/", views.layer_list, name="layer_list"),

    # Layer API endpoints
    path("all-layers/", views.all_layers, name="all_layers"),
    path("layer-preview-features/", views.layer_preview_features, name="layer_preview_features"),
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),

    # Export
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),

    # User preference endpoints
    path("user-connects/", views.user_connects, name="user_connects"),
    path("user-layer-preferences/", views.user_layer_preferences, name="user_layer_preferences"),
    path("clear-layer-preferences/", views.clear_layer_preferences, name="clear_layer_preferences"),
    path("toggle-layer-favorite/<int:layer_id>/", views.toggle_layer_favorite, name="toggle_layer_favorite"),
]