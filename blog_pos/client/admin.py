from django.contrib import admin
from .models import Client
from users.models import AppSetting


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    """Administration des clients"""
    list_display = ['name', 'phone', 'total_orders', 'total_spent', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'phone']
    readonly_fields = ['created_at', 'updated_at', 'total_orders', 'total_spent']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Informations Client', {
            'fields': ('name', 'phone', 'is_active')
        }),
        ('Statistiques', {
            'fields': ('total_orders', 'total_spent'),
            'classes': ('collapse',)
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def total_orders(self, obj):
        """Afficher le nombre total de commandes"""
        return obj.total_orders()
    total_orders.short_description = 'Commandes'
    
    def total_spent(self, obj):
        """Afficher le montant total dépensé"""
        return f"{obj.total_spent()} {AppSetting.get_currency_label()}"
    total_spent.short_description = 'Total Dépensé'