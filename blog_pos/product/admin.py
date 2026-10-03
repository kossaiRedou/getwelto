from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    search_fields = ['title']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['title', 'barcode', 'category', 'final_value', 'qty', 'prix_achat', 'active']
    list_select_related = ['category']
    list_filter = ['active', 'category']
    search_fields = ['title', 'barcode']
    list_per_page = 50
    fields = ['active', 'title', 'barcode', 'category', 'value', 'discount_value', 'prix_achat', 'qty']
    # Le stock ne change que par des mouvements tracés (vente, approvisionnement, ajustement).
    readonly_fields = ['qty']
    autocomplete_fields = ['category']
