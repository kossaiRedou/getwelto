from decimal import Decimal

from django.db import models
from django.db.models import F, Sum

from core.mixins import SyncUUIDMixin


def normalize_phone(raw):
    """Garde uniquement les chiffres (et le + initial éventuel)."""
    raw = (raw or '').strip()
    digits = ''.join(ch for ch in raw if ch.isdigit())
    return ('+' + digits) if raw.startswith('+') and digits else digits


class Client(SyncUUIDMixin):
    """Client d'une boutique (chaque boutique a ses clients et leurs crédits)."""
    shop = models.ForeignKey('accounts.Shop', on_delete=models.PROTECT, related_name='clients')
    phone = models.CharField(max_length=20, help_text="Numéro de téléphone (unique dans la boutique)")
    name = models.CharField(max_length=150, help_text="Nom complet du client")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Client actif")

    class Meta:
        ordering = ['name']
        verbose_name = "Client"
        verbose_name_plural = "Clients"
        constraints = [
            models.UniqueConstraint(fields=['shop', 'phone'], name='client_unique_phone_per_shop'),
        ]

    def __str__(self):
        return f"{self.name} ({self.phone})"

    def total_orders(self):
        return self.orders.count()

    def total_spent(self):
        return self.orders.aggregate(s=Sum('final_value'))['s'] or Decimal('0.00')

    def last_order_date(self):
        last = self.orders.order_by('-timestamp').first()
        return last.date if last else None

    def total_unpaid_amount(self):
        """Dette du client = Σ (total − déjà payé) de ses ventes non soldées."""
        return (self.orders.filter(is_paid=False)
                .aggregate(s=Sum(F('final_value') - F('amount_paid')))['s'] or Decimal('0.00'))

    @staticmethod
    def search(queryset, query, limit=10):
        """Recherche par nom ou téléphone dans `queryset` (les clients de la boutique)."""
        query = (query or '').strip()
        qs = queryset.filter(is_active=True)
        if not query:
            return qs.none()
        digits = ''.join(ch for ch in query if ch.isdigit())
        cond = models.Q(name__icontains=query)
        if digits:
            cond |= models.Q(phone__contains=digits)
        return qs.filter(cond).order_by('name')[:limit]
