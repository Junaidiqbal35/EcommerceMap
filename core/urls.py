from django.urls import path
from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("map-layers/", views.map_layers, name="map_layers"),
    path("marker-layers/", views.marker_layers, name="marker_layers"),
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),
]