from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),  # Main map page
    path("map-layers/", views.map_layers, name="map_layers"),  # Returns point/centroid for each layer
    path("marker-layers/", views.marker_layers, name="marker_layers"),  # Returns layers for a specific marker
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),  # Multi-layer DXF export
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),
]
