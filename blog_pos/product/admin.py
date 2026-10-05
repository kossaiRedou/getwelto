from django.contrib import admin

from .models import Category, Product, Stock


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['title', 'account', 'is_default']
    list_filter = ['account']
    search_fields = ['title', 'account__name']


class StockInline(admin.TabularInline):
    """Stock par boutique : consultation seule (écrit par les mouvements tracés)."""
    model = Stock
    extra = 0
    fields = ['shop', 'qty', 'updated_at']
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'account', 'barcode', 'category', 'final_value', 'prix_achat', 'active']
    list_select_related = ['category', 'account']
    list_filter = ['active', 'account']
    search_fields = ['title', 'barcode', 'account__name']
    list_per_page = 50
    fields = ['account', 'active', 'title', 'barcode', 'category', 'value', 'discount_value', 'prix_achat']
    readonly_fields = ['account']
    autocomplete_fields = ['category']
    inlines = [StockInline]

    def has_add_permission(self, request):
        return False   # les produits se créent dans l'app du client
