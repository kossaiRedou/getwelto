from django.contrib import admin

from .models import Order, OrderItem, Payment


class ReadOnlyAdmin(admin.ModelAdmin):
    """Les ventes ne se modifient que via la caisse (order.services) : consultation seule."""

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ('product', 'qty', 'final_price', 'total_price', 'cost_price')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ('date', 'method', 'amount', 'created_by', 'note')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(ReadOnlyAdmin):
    list_display = ('title', 'shop', 'date', 'client', 'final_value', 'amount_paid', 'is_paid', 'created_by')
    list_filter = ('is_paid', 'shop__account', 'date')
    search_fields = ('title', 'client__name', 'client__phone', 'shop__name', 'shop__account__name')
    list_select_related = ('shop', 'client', 'created_by')
    date_hierarchy = 'date'
    inlines = [OrderItemInline, PaymentInline]


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ('order', 'amount', 'method', 'date', 'created_by')
    list_filter = ('method', 'date')
    search_fields = ('order__title',)
