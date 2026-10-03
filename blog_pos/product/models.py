from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Q

try:
    from users.models import AppSetting
except Exception:
    AppSetting = None
from core.mixins import SyncableMixin
from .managers import ProductManager


def get_currency_label():
    try:
        if AppSetting:
            return AppSetting.get_currency_label()
    except Exception:
        pass
    return getattr(settings, 'CURRENCY', 'GNF')


# Seuil de stock faible depuis les paramètres
def get_low_stock_threshold():
    try:
        return AppSetting.get_low_stock_threshold()
    except Exception:
        return 5


# 14 chiffres dont 2 décimales : jusqu'à 999 milliards, nécessaire pour le
# franc guinéen (un sac de riz ≈ 500 000 GNF, un approvisionnement ≈ 10⁸ GNF).
MONEY = dict(max_digits=14, decimal_places=2)


class Category(SyncableMixin):
    title = models.CharField(max_length=150, unique=True)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['title']

    def __str__(self):
        return self.title


class Product(SyncableMixin):
    active = models.BooleanField(default=True)
    title = models.CharField(max_length=150, unique=True)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True,
                               help_text="Code-barres (optionnel, pour la douchette)")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL)
    value = models.DecimalField(default=Decimal('0.00'), **MONEY)
    discount_value = models.DecimalField(default=Decimal('0.00'), **MONEY)
    final_value = models.DecimalField(default=Decimal('0.00'), **MONEY)
    qty = models.PositiveIntegerField(default=0)
    prix_achat = models.DecimalField(default=Decimal('0.00'), help_text="Prix d'achat unitaire (pour la traçabilité)", **MONEY)

    objects = models.Manager()
    browser = ProductManager()

    class Meta:
        verbose_name_plural = 'Products'
        ordering = ['title']
        constraints = [
            models.CheckConstraint(condition=Q(value__gte=0), name='product_value_gte_0'),
            models.CheckConstraint(condition=Q(discount_value__gte=0), name='product_discount_value_gte_0'),
            models.CheckConstraint(condition=Q(final_value__gte=0), name='product_final_value_gte_0'),
            models.CheckConstraint(condition=Q(prix_achat__gte=0), name='product_prix_achat_gte_0'),
        ]

    def save(self, *args, **kwargs):
        if self.barcode is not None:
            self.barcode = self.barcode.strip() or None
        self.final_value = self.discount_value if self.discount_value > 0 else self.value
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def tag_final_value(self):
        return f'{self.final_value} {get_currency_label()}'
    tag_final_value.short_description = 'Value'

    def tag_prix_achat(self):
        if self.prix_achat > 0:
            return f'{self.prix_achat} {get_currency_label()}'
        return 'Non défini'
    tag_prix_achat.short_description = 'Prix d\'achat'
