from django.urls import path
from . import views

urlpatterns = [
    # Main map page
    path("", views.home, name="home"),

    # API endpoints
    path("all-layers/", views.all_layers, name="all_layers"),
    path("layer-preview-features/", views.layer_preview_features, name="layer_preview_features"),
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),
    path("layer-feature-bounds/", views.layer_feature_bounds, name="layer_feature_bounds"),
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),
    path("check-connects/", views.check_connects, name="check_connects"),
]