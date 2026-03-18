import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'EcommerceMap.settings')

app = Celery('EcommerceMap')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()


app.conf.beat_schedule = {
    'daily-layer-maintenance': {
        'task': 'core.tasks.daily_layer_maintenance',
        'schedule': crontab(hour=23, minute=0),
    },
}