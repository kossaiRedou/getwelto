from django.contrib import admin
from .models import TypeDepense, Depense, MouvementStock


@admin.register(TypeDepense)
class TypeDepenseAdmin(admin.ModelAdmin):
    list_display = ['nom', 'description', 'couleur', 'actif', 'created_at']
    list_filter = ['actif', 'created_at']
    search_fields = ['nom', 'description']
    list_editable = ['actif', 'couleur']


@admin.register(Depense)
class DepenseAdmin(admin.ModelAdmin):
    list_display = ['description', 'type_depense', 'tag_montant', 'date_depense', 'fournisseur', 'created_at']
    list_filter = ['type_depense', 'date_depense', 'created_at']
    search_fields = ['description', 'fournisseur', 'reference']
    date_hierarchy = 'date_depense'
    readonly_fields = ['created_at', 'created_by']
    
    fieldsets = (
        ('Informations principales', {
            'fields': ('type_depense', 'description', 'montant', 'date_depense')
        }),
        ('Détails fournisseur', {
            'fields': ('fournisseur', 'reference'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        ('Métadonnées', {
            'fields': ('created_at', 'created_by'),
            'classes': ('collapse',)
        })
    )

    def save_model(self, request, obj, form, change):
        if not change:  # Nouveau objet
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(MouvementStock)
class MouvementStockAdmin(admin.ModelAdmin):
    """Journal de stock : consultation seule (écrit uniquement par aprovision.services)."""
    list_display = ['produit', 'type_mouvement', 'quantite', 'stock_avant', 'stock_apres',
                    'prix_achat_unitaire', 'date_mouvement', 'created_by']
    list_filter = ['type_mouvement', 'date_mouvement', 'produit__category']
    search_fields = ['produit__title', 'description']
    date_hierarchy = 'date_mouvement'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False