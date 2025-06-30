# Add these demo URLs to your core/urls.py

from django.urls import path
from . import views

urlpatterns = [
    # Existing URLs...
    path("", views.home, name="home"),



    # Demo endpoints for testing
    path("server-coverage/", views.demo_server_coverage, name="demo_server_coverage"),
    path("all-layers/", views.demo_all_layers, name="demo_all_layers"),
    path("layer-preview-features/", views.demo_layer_preview_features, name="demo_layer_preview_features"),
    path("nearby-layers/", views.demo_nearby_layers, name="demo_nearby_layers"),
    path("export-dxf-multi/", views.demo_export_dxf_multi, name="demo_export_dxf_multi"),


]