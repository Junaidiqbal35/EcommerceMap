from django.contrib import admin
from django.urls import path, include
admin.site.site_header = "EcommerceMap Admin"
admin.site.site_title = "EcommerceMap Portal"
admin.site.index_title = "Welcome to EcommerceMap Portal"
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),

]
