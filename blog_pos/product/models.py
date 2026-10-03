import re
from decimal import Decimal

from django.conf import settings
from django.core.validators import RegexValidator
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


# Couleurs proposées pour les catégories et les produits : assez foncées pour
# que les initiales en blanc restent lisibles, sur fond clair comme sombre.
PALETTE = [
    ('#2563eb', 'Bleu'), ('#16a34a', 'Vert'), ('#dc2626', 'Rouge'), ('#ea580c', 'Orange'),
    ('#7c3aed', 'Violet'), ('#0891b2', 'Cyan'), ('#db2777', 'Rose'), ('#ca8a04', 'Jaune'),
    ('#0d9488', 'Turquoise'), ('#9333ea', 'Mauve'), ('#65a30d', 'Olive'), ('#92400e', 'Marron'),
]
DEFAULT_CATEGORY_TITLE = 'Autres'
DEFAULT_CATEGORY_COLOR = '#64748b'
COLOR_CHOICES = PALETTE + [(DEFAULT_CATEGORY_COLOR, 'Gris')]
hex_color = RegexValidator(r'^#[0-9a-f]{6}$', 'Couleur invalide.')


def initials(title):
    """« Coca-Cola 1L » → « CC » ; « Riz 5kg » → « R5 »."""
    words = [w for w in re.split(r'[\s\-_/.,]+', title or '') if w]
    letters = ''.join(w[0] for w in words[:2]).upper()
    return letters or '?'


class Category(SyncableMixin):
    title = models.CharField(max_length=150, unique=True)
    color = models.CharField(max_length=7, blank=True, validators=[hex_color],
                             help_text="Couleur des produits de la catégorie à la caisse")
    is_default = models.BooleanField(default=False, editable=False,
                                     help_text="Catégorie « Autres » : celle des produits sans catégorie")

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['-is_default', 'title']
        constraints = [
            models.UniqueConstraint(fields=['is_default'], condition=Q(is_default=True),
                                    name='category_single_default'),
        ]

    def __str__(self):
        return self.title

    @classmethod
    def get_default(cls):
        category = cls.objects.filter(is_default=True).first()
        if category is None:
            category, _ = cls.objects.get_or_create(
                title=DEFAULT_CATEGORY_TITLE, defaults={'color': DEFAULT_CATEGORY_COLOR})
            if not category.is_default:
                cls.objects.filter(pk=category.pk).update(is_default=True)
                category.is_default = True
        return category

    @staticmethod
    def next_color():
        """Couleur de la palette la moins utilisée par les catégories existantes."""
        used = list(Category.objects.values_list('color', flat=True))
        return min((c for c, _ in PALETTE), key=lambda c: (used.count(c), [p for p, _ in PALETTE].index(c)))

    def save(self, *args, **kwargs):
        self.color = (self.color or '').lower()
        if not self.color:
            self.color = DEFAULT_CATEGORY_COLOR if self.is_default else self.next_color()
        super().save(*args, **kwargs)


class Product(SyncableMixin):
    active = models.BooleanField(default=True)
    title = models.CharField(max_length=150, unique=True)
    barcode = models.CharField(max_length=64, unique=True, null=True, blank=True,
                               help_text="Code-barres (optionnel, pour la douchette)")
    category = models.ForeignKey(Category, blank=True, on_delete=models.PROTECT,
                                 help_text="« Autres » si aucune catégorie n'est choisie")
    color = models.CharField(max_length=7, blank=True, validators=[hex_color],
                             help_text="Vide : couleur de la catégorie")
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
        self.color = (self.color or '').lower()
        if self.category_id is None:
            self.category = Category.get_default()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    @property
    def display_color(self):
        return self.color or (self.category.color if self.category_id else '') or DEFAULT_CATEGORY_COLOR

    @property
    def initials(self):
        return initials(self.title)

    def tag_final_value(self):
        return f'{self.final_value} {get_currency_label()}'
    tag_final_value.short_description = 'Value'

    def tag_prix_achat(self):
        if self.prix_achat > 0:
            return f'{self.prix_achat} {get_currency_label()}'
        return 'Non défini'
    tag_prix_achat.short_description = 'Prix d\'achat'
