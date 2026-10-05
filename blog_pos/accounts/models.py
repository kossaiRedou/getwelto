"""
Comptes clients du SaaS WELTO.

Un compte = une entreprise dans un pays, avec une seule devise. Il a un gérant
(le patron) et une ou plusieurs boutiques, chacune avec ses employés, son stock,
ses clients et ses ventes. Le catalogue de produits est commun au compte.

Le propriétaire du SaaS active le compte, choisit sa date de fin et le nombre
de boutiques autorisées depuis l'admin Django. Aucun paiement en ligne.
"""
import re
import unicodedata

from django.db import models
from django.db.models import Q
from django.utils import timezone

# Pays proposés à l'inscription et leur devise (un compte = un pays = une devise).
COUNTRIES = [
    ('GN', 'Guinée', 'GNF'),
    ('GM', 'Gambie', 'GMD'),
    ('SN', 'Sénégal', 'XOF'),
    ('ML', 'Mali', 'XOF'),
    ('CI', "Côte d'Ivoire", 'XOF'),
    ('GW', 'Guinée-Bissau', 'XOF'),
    ('SL', 'Sierra Leone', 'SLE'),
    ('LR', 'Liberia', 'LRD'),
    ('MR', 'Mauritanie', 'MRU'),
]
COUNTRY_CHOICES = [(code, name) for code, name, _ in COUNTRIES]
CURRENCY_BY_COUNTRY = {code: currency for code, _, currency in COUNTRIES}
EXPIRY_WARNING_DAYS = 7


class Account(models.Model):
    name = models.CharField('Entreprise', max_length=150)
    country = models.CharField('Pays', max_length=2, choices=COUNTRY_CHOICES)
    currency = models.CharField('Devise', max_length=10,
                                help_text="Affichée sur tous les montants (ex : GNF, GMD, XOF).")
    phone = models.CharField('Téléphone', max_length=30, blank=True)
    email = models.EmailField('Email', blank=True)

    is_active = models.BooleanField('Actif', default=False,
                                    help_text="Décoché : personne du compte ne peut se connecter.")
    active_until = models.DateField('Actif jusqu\'au', null=True, blank=True,
                                    help_text="Dernier jour d'accès inclus. Vide : sans date de fin.")
    max_shops = models.PositiveSmallIntegerField('Boutiques autorisées', default=1)
    admin_notes = models.TextField('Notes internes', blank=True,
                                   help_text="Visible uniquement dans l'admin (paiements reçus, contact…).")
    created_at = models.DateTimeField('Inscrit le', auto_now_add=True)

    class Meta:
        verbose_name = 'Compte client'
        verbose_name_plural = 'Comptes clients'
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=Q(max_shops__gte=1), name='account_max_shops_gte_1'),
        ]

    def __str__(self):
        return self.name

    # ------------------------------------------------------------ abonnement
    @property
    def is_open(self):
        """Le compte peut-il se connecter aujourd'hui ?"""
        return self.is_active and (self.active_until is None or self.active_until >= timezone.localdate())

    @property
    def days_left(self):
        """Jours restants (0 = dernier jour), None sans date de fin."""
        if self.active_until is None:
            return None
        return (self.active_until - timezone.localdate()).days

    @property
    def expires_soon(self):
        days = self.days_left
        return self.is_open and days is not None and days <= EXPIRY_WARNING_DAYS

    @property
    def status(self):
        if not self.is_active:
            return 'pending' if self.active_until is None else 'suspended'
        if not self.is_open:
            return 'expired'
        return 'soon' if self.expires_soon else 'active'

    def blocked_message(self):
        """Message affiché à la connexion d'un compte qui ne peut pas entrer."""
        if self.status == 'pending':
            return "Votre compte est en attente d'activation. Vous serez contacté très vite."
        if self.status == 'expired':
            return (f"Votre abonnement a pris fin le {self.active_until:%d/%m/%Y}. "
                    "Contactez votre fournisseur WELTO pour le renouveler.")
        return 'Votre compte est suspendu. Contactez votre fournisseur WELTO.'

    # ------------------------------------------------------------ boutiques
    def can_add_shop(self):
        return self.shops.count() < self.max_shops

    @property
    def manager(self):
        return self.users.filter(role='manager').first()


def _code_from_name(name):
    ascii_name = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode()
    letters = re.sub(r'[^A-Za-z]', '', ascii_name).upper()
    return (letters[:3] or 'BTQ').ljust(3, 'X')


class Shop(models.Model):
    account = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='shops', verbose_name='Compte')
    name = models.CharField('Nom', max_length=150)
    code = models.CharField('Code', max_length=6,
                            help_text="2 à 6 lettres ou chiffres, en tête des numéros de vente (ex : KAL-000123).")
    address = models.CharField('Adresse', max_length=200, blank=True)
    phone = models.CharField('Téléphone', max_length=30, blank=True)
    is_active = models.BooleanField('Active', default=True)
    next_number = models.PositiveIntegerField('Dernier numéro de vente', default=0, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Boutique'
        verbose_name_plural = 'Boutiques'
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['account', 'code'], name='shop_unique_code_per_account'),
            models.UniqueConstraint(fields=['account', 'name'], name='shop_unique_name_per_account'),
        ]

    def __str__(self):
        return self.name

    @classmethod
    def free_code(cls, account, name):
        """Code court libre dans le compte, tiré du nom (« Kaloum » → KAL, puis KAL2…)."""
        base = _code_from_name(name)
        taken = set(cls.objects.filter(account=account).values_list('code', flat=True))
        if base not in taken:
            return base
        n = 2
        while f'{base}{n}' in taken:
            n += 1
        return f'{base}{n}'

    def save(self, *args, **kwargs):
        self.code = (self.code or '').strip().upper() or self.free_code(self.account, self.name)
        super().save(*args, **kwargs)
