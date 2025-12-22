from django.urls import path
from . import views

urlpatterns = [
    # Main map page
    path("", views.home, name="home"),

    # API endpoints - Layers
    path("all-layers/", views.all_layers, name="all_layers"),
    path("layers/", views.all_layers, name="layer_list"),  # HTMX endpoint
    path("layer-preview-features/", views.layer_preview_features, name="layer_preview_features"),
    path("nearby-layers/", views.nearby_layers, name="nearby_layers"),  # GET and POST
    path("export-dxf-multi/", views.export_dxf_multi, name="export_dxf_multi"),
    
    # API endpoints - User Preferences
    path("api/preferences/", views.get_user_preferences, name="get_user_preferences"),
    path("api/preferences/toggle-favorite/", views.toggle_favorite_layer, name="toggle_favorite_layer"),
    path("api/preferences/save/", views.save_layer_selection, name="save_layer_selection"),
    path("api/preferences/clear/", views.clear_preferences, name="clear_preferences"),
]