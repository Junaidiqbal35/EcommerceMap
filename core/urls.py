from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='home'),
    path('servers/', views.ServerListAPIView.as_view(), name='server-list'),
    path('layers/', views.LayerListAPIView.as_view(), name='layer-list'),
    # path('layers/download/<int:layer_id>/', views.download_layer, name='download_layer'),
    # path('export-layer/<int:layer_id>/dxf/', views.export_layer_to_dxf, name='export_layer_to_dxf'),
    path('export-dxf/', views.export_dxf, name='export_dxf'),
    path('info/', views.get_layer_info, name='get_layer_info'),

]
