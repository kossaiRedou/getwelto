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
    """Paramètres globaux personnalisables par le manager"""
    currency_label = models.CharField(
        max_length=10,
        default='GMD',
        verbose_name=_('Devise (label)'),
        help_text=_('Exemple: GMD, FCFA, CFA, €')
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
        return f"Paramètres ({self.currency_label}, seuil {self.low_stock_threshold})"

    @classmethod
    def get_solo(cls) -> 'AppSetting':
        obj, _ = cls.objects.get_or_create(id=1)
        return obj

    @classmethod
    def get_currency_label(cls) -> str:
        return cls.get_solo().currency_label or 'GMD'

    @classmethod
    def get_low_stock_threshold(cls) -> int:
        return cls.get_solo().low_stock_threshold or 5


class PasswordResetCode(models.Model):
    """Code de réinitialisation de mot de passe envoyé par email.

    Le code (6 chiffres) n'est jamais stocké en clair : seul son hash est
    conservé. Chaque code a une durée de validité courte et un nombre limité
    d'essais. Une nouvelle demande invalide les codes précédents de l'utilisateur.
    """
    VALIDITY_MINUTES = 15
    MAX_ATTEMPTS = 5

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reset_codes')
    code_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Code de réinitialisation'
        verbose_name_plural = 'Codes de réinitialisation'
        ordering = ['-created_at']

    def __str__(self):
        return f'Code reset {self.user.username} ({"utilisé" if self.used else "actif"})'

    @property
    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def is_valid(self):
        return (not self.used) and (not self.is_expired) and self.attempts < self.MAX_ATTEMPTS

    @classmethod
    def issue_for(cls, user):
        """Génère un nouveau code pour l'utilisateur et renvoie (instance, code_clair)."""
        import secrets
        from datetime import timedelta

        from django.contrib.auth.hashers import make_password
        from django.utils import timezone

        # Invalider les anciens codes non utilisés
        cls.objects.filter(user=user, used=False).update(used=True)

        code = f'{secrets.randbelow(1000000):06d}'  # 000000..999999
        instance = cls.objects.create(
            user=user,
            code_hash=make_password(code),
            expires_at=timezone.now() + timedelta(minutes=cls.VALIDITY_MINUTES),
        )
        return instance, code

    def register_attempt(self):
        """Incrémente le compteur d'essais de façon atomique."""
        type(self).objects.filter(pk=self.pk).update(attempts=models.F('attempts') + 1)
        self.refresh_from_db(fields=['attempts'])

    def check_code(self, raw_code):
        """Compare un code saisi au hash stocké (temps constant)."""
        from django.contrib.auth.hashers import check_password
        return check_password((raw_code or '').strip(), self.code_hash)
