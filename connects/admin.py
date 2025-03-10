# Register your models here.
from django.contrib import admin
from .models import ConnectPackage, ConnectTransaction, ConnectUsage


@admin.register(ConnectPackage)
class ConnectPackageAdmin(admin.ModelAdmin):
    list_display = ('name', 'connects', 'price', 'created_at')
    search_fields = ('name',)
    list_filter = ('created_at',)


@admin.register(ConnectTransaction)
class ConnectTransactionAdmin(admin.ModelAdmin):
    list_display = ('user', 'connects_added', 'amount_paid', 'created_at', 'stripe_session_id')
    search_fields = ('user__username', 'stripe_session_id')
    list_filter = ('created_at', 'amount_paid')


@admin.register(ConnectUsage)
class ConnectUsageAdmin(admin.ModelAdmin):
    list_display = ('user', 'layer', 'connects_used', 'timestamp')
    search_fields = ('user__username', 'layer__name')
    list_filter = ('timestamp',)
