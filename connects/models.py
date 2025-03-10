# Create your models here.
from django.db import models
from django.conf import settings


from core.models import Layer


class ConnectPackage(models.Model):
    name = models.CharField(max_length=100)
    connects = models.IntegerField()
    price = models.DecimalField(max_digits=6, decimal_places=2)
    stripe_plan_id = models.CharField(max_length=40, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.connects} connects for ${self.price}"


class ConnectTransaction(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    package = models.ForeignKey(ConnectPackage, on_delete=models.SET_NULL, null=True)
    stripe_session_id = models.CharField(max_length=255, blank=True, null=True)
    amount_paid = models.DecimalField(max_digits=6, decimal_places=2)
    connects_added = models.IntegerField()
    is_completed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.connects_added} connects on {self.created_at}"


class ConnectUsage(models.Model):

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    layer = models.ForeignKey(Layer, on_delete=models.CASCADE)
    connects_used = models.IntegerField(default=1)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} used {self.connects_used} connects for {self.layer.name} on {self.timestamp}"
