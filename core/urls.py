from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='index'),
    path('api/servers/', views.ServerListAPIView.as_view(), name='server-list'),
    path('api/layers/', views.LayerListAPIView.as_view(), name='layer-list'),
    # path('layers/', views.get_layers, name='get_layers'),

]
