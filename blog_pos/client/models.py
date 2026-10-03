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
    phone = models.CharField(max_length=20, unique=True, help_text="Numéro de téléphone (unique)")
    name = models.CharField(max_length=150, help_text="Nom complet du client")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, help_text="Client actif")

    class Meta:
        ordering = ['name']
        verbose_name = "Client"
        verbose_name_plural = "Clients"

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

    @classmethod
    def search(cls, query, limit=10):
        query = (query or '').strip()
        qs = cls.objects.filter(is_active=True)
        if not query:
            return qs.none()
        digits = ''.join(ch for ch in query if ch.isdigit())
        cond = models.Q(name__icontains=query)
        if digits:
            cond |= models.Q(phone__contains=digits)
        return qs.filter(cond).order_by('name')[:limit]
