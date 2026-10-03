from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

from core.mixins import SyncableMixin

def _currency():
    from users.models import AppSetting
    return AppSetting.get_currency_label()


class TypeDepense(SyncableMixin):
    """Types de dépenses pour catégoriser les dépenses"""
    nom = models.CharField(max_length=100, unique=True, help_text="Ex: Approvisionnement, Matériel, Main d'œuvre")
    description = models.TextField(blank=True, help_text="Description du type de dépense")
    couleur = models.CharField(max_length=7, default="#007bff", help_text="Couleur hex pour l'affichage")
    actif = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Type de Dépense"
        verbose_name_plural = "Types de Dépenses"
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Depense(SyncableMixin):
    """Enregistrement des dépenses du commerce"""
    type_depense = models.ForeignKey(TypeDepense, on_delete=models.PROTECT, related_name='depenses')
    description = models.CharField(max_length=200, help_text="Description de la dépense")
    montant = models.DecimalField(max_digits=14, decimal_places=2, help_text="Montant de la dépense")
    date_depense = models.DateField(default=timezone.localdate, help_text="Date de la dépense")
    
    # Champs optionnels
    fournisseur = models.CharField(max_length=150, blank=True, help_text="Nom du fournisseur (optionnel)")
    reference = models.CharField(max_length=50, blank=True, help_text="Numéro de facture ou référence")
    notes = models.TextField(blank=True, help_text="Notes additionnelles")
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Dépense"
        verbose_name_plural = "Dépenses"
        ordering = ['-date_depense', '-created_at']
        constraints = [
            models.CheckConstraint(condition=models.Q(montant__gt=0), name='depense_montant_gt_0'),
        ]

    def __str__(self):
        return f"{self.description} - {self.montant} {_currency()}"

    def tag_montant(self):
        return f"{self.montant} {_currency()}"
    tag_montant.short_description = "Montant"


class TypeMouvement(models.TextChoices):
    """Types de mouvements de stock"""
    ENTREE = 'ENTREE', 'Entrée (Approvisionnement)'
    SORTIE_VENTE = 'SORTIE_VENTE', 'Sortie (Vente)'
    SORTIE_PERTE = 'SORTIE_PERTE', 'Sortie (Perte/Casse)'
    AJUSTEMENT_PLUS = 'AJUSTEMENT_PLUS', 'Ajustement +'
    AJUSTEMENT_MOINS = 'AJUSTEMENT_MOINS', 'Ajustement -'


class MouvementStock(SyncableMixin):
    """Traçabilité des mouvements de stock"""
    produit = models.ForeignKey('product.Product', on_delete=models.CASCADE, related_name='mouvements')
    type_mouvement = models.CharField(max_length=20, choices=TypeMouvement.choices)
    quantite = models.IntegerField(help_text="Quantité (positive pour entrée, négative pour sortie)")
    
    # Stock avant et après le mouvement
    stock_avant = models.PositiveIntegerField(help_text="Stock avant le mouvement")
    stock_apres = models.PositiveIntegerField(help_text="Stock après le mouvement")
    
    # Informations sur les prix (pour les entrées)
    prix_achat_unitaire = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True,
                                            help_text="Prix d'achat unitaire (pour les entrées)")
    cout_total = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True,
                                   help_text="Coût total du mouvement")
    
    # Références
    reference_commande = models.ForeignKey('order.Order', on_delete=models.SET_NULL, null=True, blank=True,
                                         help_text="Commande associée (pour les ventes)")
    reference_depense = models.ForeignKey(Depense, on_delete=models.SET_NULL, null=True, blank=True,
                                        help_text="Dépense associée (pour les approvisionnements)")
    
    # Métadonnées
    description = models.CharField(max_length=200, blank=True, help_text="Description du mouvement")
    date_mouvement = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = "Mouvement de Stock"
        verbose_name_plural = "Mouvements de Stock"
        ordering = ['-date_mouvement', '-id']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_apres=models.F('stock_avant') + models.F('quantite')),
                name='mouvement_stock_coherent'),
        ]

    def __str__(self):
        signe = "+" if self.quantite > 0 else ""
        return f"{self.produit.title} - {signe}{self.quantite} ({self.get_type_mouvement_display()})"

    @property
    def is_entry(self):
        return self.quantite > 0