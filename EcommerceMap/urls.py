from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.conf.urls.static import static
from django_celery_beat.models import (
        PeriodicTask,
        IntervalSchedule,
        CrontabSchedule,
        SolarSchedule,
        ClockedSchedule,
    )
admin.site.site_header = "EcommerceMap Admin"
admin.site.site_title = "EcommerceMap Portal"
admin.site.index_title = "Welcome to EcommerceMap Portal"

admin.site.unregister(PeriodicTask)
admin.site.unregister(IntervalSchedule)
admin.site.unregister(CrontabSchedule)
admin.site.unregister(SolarSchedule)
admin.site.unregister(ClockedSchedule)
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),
    path('connects/', include('connects.urls')),

]+ static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
