from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django.views.generic import TemplateView
from core import views

admin.site.site_header = "EcommerceMap Admin"
admin.site.site_title = "EcommerceMap Portal"
admin.site.index_title = "Welcome to EcommerceMap Portal"
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
