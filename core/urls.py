from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('servers/', views.ServerListAPIView.as_view(), name='server-list'),
    path('layers/', views.LayerListAPIView.as_view(), name='layer-list'),
    path('layers/download/<int:layer_id>/', views.download_layer, name='download_layer'),
    # path('layers/', views.get_layers, name='get_layers'),

]
