from django.db import models
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Modèle utilisateur personnalisé avec rôles"""

    ROLE_CHOICES = [
        ('manager', 'Manager'),
        ('employee', 'Employé'),
    ]
    
    # Champs personnalisés
    role = models.CharField(
        max_length=10,
        choices=ROLE_CHOICES,
        default='employee',
        verbose_name='Rôle'
    )
    
    phone = models.CharField(
        max_length=15,
        blank=True,
        null=True,
        verbose_name='Téléphone'
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name='Compte actif'
    )
    
    account = models.ForeignKey(
        'accounts.Account',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='users',
        verbose_name='Compte client',
        help_text="Vide pour le propriétaire du SaaS (accès à l'admin uniquement)."
    )

    shop = models.ForeignKey(
        'accounts.Shop',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='employees',
        verbose_name='Boutique',
        help_text="Boutique de l'employé (le gérant voit toutes les boutiques)."
    )

    created_by = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_users',
        verbose_name='Créé par'
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date de création'
    )

    # Métadonnées
    class Meta:
        verbose_name = 'Utilisateur'
        verbose_name_plural = 'Utilisateurs'
        ordering = ['-created_at']
        constraints = [
            # Un seul gérant (le patron) par compte client.
            models.UniqueConstraint(fields=['account'], condition=models.Q(role='manager'),
                                    name='user_single_manager_per_account'),
        ]
    
    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display()})"
    
    def get_role_display(self):
        """Retourne le nom du rôle"""
        return dict(self.ROLE_CHOICES).get(self.role, 'Inconnu')
    
    def is_manager(self):
        """Vérifie si l'utilisateur est manager"""
        return self.role == 'manager'
    
    def is_employee(self):
        """Vérifie si l'utilisateur est employé"""
        return self.role == 'employee'
    
    def can_manage_users(self):
        """Vérifie si l'utilisateur peut gérer les utilisateurs"""
        return self.is_manager()
    
    def can_manage_products(self):
        """Vérifie si l'utilisateur peut gérer les produits"""
        return self.is_manager()
    
    def can_manage_orders(self):
        """Vérifie si l'utilisateur peut gérer les commandes"""
        return True  # Tous les utilisateurs peuvent gérer les commandes
    
    def can_manage_clients(self):
        """Vérifie si l'utilisateur peut gérer les clients"""
        return True  # Tous les utilisateurs peuvent gérer les clients
    
    def can_manage_aprovision(self):
        """Vérifie si l'utilisateur peut gérer les approvisionnements"""
        return self.is_manager()
    
    def can_view_analytics(self):
        """Vérifie si l'utilisateur peut voir les analytics"""
        return self.is_manager()
    
    def can_edit_orders(self):
        """Vérifie si l'utilisateur peut modifier les commandes (pour paiements)"""
        return True  # Tous les utilisateurs peuvent modifier les commandes pour les paiements


class UserProfile(models.Model):
    """Profil étendu pour les utilisateurs"""
    
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='Utilisateur'
    )
    
    address = models.TextField(
        blank=True,
        null=True,
        verbose_name='Adresse'
    )
    
    birth_date = models.DateField(
        blank=True,
        null=True,
        verbose_name='Date de naissance'
    )
    
    hire_date = models.DateField(
        blank=True,
        null=True,
        verbose_name='Date d\'embauche'
    )
    
    salary = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name='Salaire'
    )
    
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='Notes'
    )
    
    # Métadonnées
    class Meta:
        verbose_name = 'Profil utilisateur'
        verbose_name_plural = 'Profils utilisateurs'
    
    def __str__(self):
        return f"Profil de {self.user.get_full_name()}"


class AppSetting(models.Model):
    """Identité et réglages d'un compte client (communs à ses boutiques).

    La devise est celle du compte (un compte = un pays = une devise).
    """
    account = models.OneToOneField(
        'accounts.Account',
        on_delete=models.CASCADE,
        related_name='app_settings',
        verbose_name='Compte client',
    )
    low_stock_threshold = models.PositiveIntegerField(
        default=5,
        verbose_name=_('Seuil d\'alerte stock'),
        help_text=_('Stock sous lequel un produit est considéré en stock faible')
    )
    company_name = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name=_('Nom de l\'entreprise'),
        help_text=_('Nom commercial affiché sur les factures et l\'interface')
    )
    company_logo = models.ImageField(
        upload_to='logos/',
        null=True,
        blank=True,
        verbose_name=_('Logo de l\'entreprise'),
        help_text=_('Image du logo (PNG/JPG). Affichée sur les factures et l\'interface')
    )
    company_tagline = models.CharField(
        max_length=80,
        blank=True,
        default='',
        verbose_name=_('Slogan / Activité'),
        help_text=_('Court descriptif affiché sous le nom sur les factures (max 80 car.). Ex: Boutique de vêtements, Restaurant, etc.')
    )
    brand_color_primary = models.CharField(
        max_length=7,
        default='#3d35e6',
        verbose_name=_('Couleur principale'),
        help_text=_('Couleur principale de l\'entreprise (titres, barres)')
    )
    brand_color_secondary = models.CharField(
        max_length=7,
        default='#198754',
        verbose_name=_('Couleur secondaire'),
        help_text=_('Couleur secondaire (accents, montants payés)')
    )
    brand_color_accent = models.CharField(
        max_length=7,
        default='#dc3545',
        verbose_name=_('Couleur d\'accent'),
        help_text=_('Couleur d\'accent (alertes, montants restants)')
    )
    signature_image = models.ImageField(
        upload_to='signatures/',
        null=True,
        blank=True,
        verbose_name=_('Signature du responsable'),
        help_text=_('Image de signature manuscrite (PNG fond transparent recommandé)')
    )
    stamp_image = models.ImageField(
        upload_to='stamps/',
        null=True,
        blank=True,
        verbose_name=_('Cachet / Tampon'),
        help_text=_('Image du cachet d\'entreprise (PNG fond transparent recommandé)')
    )
    signatory_name = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name=_('Nom du signataire'),
        help_text=_('Nom + titre affichés sous la signature. Ex: Aliou Diallo - Gérant')
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('Paramètre de l\'application')
        verbose_name_plural = _('Paramètres de l\'application')

    def __str__(self):
        return f"Paramètres de {self.account}"

    @property
    def currency_label(self):
        return self.account.currency if self.account_id else 'GNF'

    @classmethod
    def for_account(cls, account) -> 'AppSetting':
        obj, _ = cls.objects.select_related('account').get_or_create(
            account=account, defaults={'company_name': account.name})
        return obj

    @classmethod
    def get_solo(cls) -> 'AppSetting':
        """Paramètres du compte de la requête en cours (valeurs par défaut hors requête)."""
        from accounts.scope import current_account
        account = current_account()
        return cls.for_account(account) if account else cls()

    @classmethod
    def get_currency_label(cls) -> str:
        from accounts.scope import current_account
        account = current_account()
        return account.currency if account else 'GNF'

    @classmethod
    def get_low_stock_threshold(cls) -> int:
        return cls.get_solo().low_stock_threshold or 5
