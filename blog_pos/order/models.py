"""
Ventes WELTO.

Les montants d'une vente ne sont JAMAIS calculés dans les save() : seules les
fonctions de `order.services` créent ou modifient ventes, lignes et paiements,
dans une transaction. Les contraintes de base de données ci-dessous garantissent
la cohérence même en cas de bug applicatif.
"""
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.db.models import F, Q, Sum
from django.urls import reverse
from django.utils import timezone

try:
    from users.models import AppSetting
except Exception:
    AppSetting = None
from product.models import Product
from core.mixins import SyncableMixin

ZERO = Decimal('0.00')


def get_currency_label():
    try:
        if AppSetting:
            return AppSetting.get_currency_label()
    except Exception:
        pass
    return settings.CURRENCY


class PaymentMethod(models.TextChoices):
    CASH = 'cash', 'Espèces'
    MOBILE = 'mobile', 'Mobile Money'
    CARD = 'card', 'Carte'


class Order(SyncableMixin):
    shop = models.ForeignKey('accounts.Shop', on_delete=models.PROTECT, related_name='orders')
    date = models.DateField(default=timezone.localdate)
    title = models.CharField(blank=True, max_length=150, help_text="Numéro de vente (KAL-000123)")
    timestamp = models.DateTimeField(default=timezone.now)
    value = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Sous-total des lignes")
    discount = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20)
    final_value = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Total à payer")
    amount_paid = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Somme des paiements")
    is_paid = models.BooleanField(default=False)
    client = models.ForeignKey('client.Client', on_delete=models.PROTECT, null=True, blank=True,
                               related_name='orders', help_text="Client (obligatoire pour une vente à crédit)")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='sales', help_text="Vendeur")

    objects = models.Manager()

    class Meta:
        ordering = ['-timestamp']
        constraints = [
            models.UniqueConstraint(fields=['shop', 'title'], name='order_unique_title_per_shop'),
            models.CheckConstraint(condition=Q(value__gte=0), name='order_value_gte_0'),
            models.CheckConstraint(condition=Q(discount__gte=0), name='order_discount_gte_0'),
            models.CheckConstraint(condition=Q(discount__lte=F('value')), name='order_discount_lte_value'),
            models.CheckConstraint(condition=Q(final_value=F('value') - F('discount')), name='order_final_value_eq'),
            models.CheckConstraint(condition=Q(amount_paid__gte=0), name='order_amount_paid_gte_0'),
            models.CheckConstraint(condition=Q(amount_paid__lte=F('final_value')), name='order_amount_paid_lte_final'),
            models.CheckConstraint(
                condition=(Q(is_paid=True, amount_paid=F('final_value'))
                           | Q(is_paid=False, amount_paid__lt=F('final_value'))),
                name='order_is_paid_consistent'),
        ]
        indexes = [
            models.Index(fields=['date']),
            models.Index(fields=['is_paid']),
        ]

    def __str__(self):
        return self.title or f'Vente #{self.pk}'

    def save(self, *args, **kwargs):
        if not self.title:
            # Numéro suivant de la boutique (KAL-000124), sous verrou : jamais deux fois le même.
            from accounts.models import Shop
            with transaction.atomic():
                shop = Shop.objects.select_for_update().get(pk=self.shop_id)
                Shop.objects.filter(pk=shop.pk).update(next_number=shop.next_number + 1)
                self.title = f'{shop.code}-{shop.next_number + 1:06d}'
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('order_detail', kwargs={'pk': self.pk})

    def remaining_amount(self):
        return self.final_value - self.amount_paid

    def payment_percentage(self):
        if self.final_value <= 0:
            return 100
        return int(self.amount_paid * 100 / self.final_value)

    def client_display(self):
        if self.client:
            return f"{self.client.name} ({self.client.phone})"
        return 'Client comptoir'

    def total_payments(self):
        """Somme recalculée depuis les paiements (sert aux contrôles de cohérence)."""
        return self.payments.aggregate(s=Sum('amount'))['s'] or ZERO


class OrderItem(SyncableMixin):
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='order_items')
    qty = models.PositiveIntegerField(default=1)
    price = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Prix normal au moment de la vente")
    discount_price = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Prix promo au moment de la vente")
    final_price = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Prix unitaire appliqué")
    total_price = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="qty × final_price")
    cost_price = models.DecimalField(default=ZERO, decimal_places=2, max_digits=20, help_text="Prix d'achat unitaire au moment de la vente")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['order', 'product'], name='orderitem_unique_product_per_order'),
            models.CheckConstraint(condition=Q(qty__gte=1), name='orderitem_qty_gte_1'),
            models.CheckConstraint(condition=Q(final_price__gte=0), name='orderitem_final_price_gte_0'),
            models.CheckConstraint(condition=Q(total_price__gte=0), name='orderitem_total_price_gte_0'),
        ]

    def __str__(self):
        return f'{self.product.title} × {self.qty}'

    @property
    def catalog_price(self):
        """Prix affiché au catalogue au moment de la vente (promo comprise)."""
        return self.discount_price if self.discount_price > 0 else self.price

    @property
    def price_overridden(self):
        """Vrai si le vendeur a fixé un autre prix pour cette vente (prix client)."""
        return self.final_price != self.catalog_price


class Payment(SyncableMixin):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=20, decimal_places=2, help_text="Montant du paiement")
    date = models.DateField(default=timezone.localdate, help_text="Date du paiement")
    method = models.CharField(max_length=20, choices=PaymentMethod.choices, default=PaymentMethod.CASH)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='payments_received')

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(amount__gt=0), name='payment_amount_gt_0'),
        ]

    def __str__(self):
        return f'{self.amount} {get_currency_label()} - {self.get_method_display()}'
