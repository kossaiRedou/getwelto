import re

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from core.forms import StyledFormMixin
from .models import AppSetting, User

def _validate_new_password_pair(cleaned_data):
    p1 = cleaned_data.get('new_password1')
    p2 = cleaned_data.get('new_password2')
    if p1 and p2:
        if p1 != p2:
            raise ValidationError('Les mots de passe ne correspondent pas.')
        if len(p1) < 8:
            raise ValidationError('Le mot de passe doit contenir au moins 8 caractères.')
    return cleaned_data


def _password_field(label):
    return forms.CharField(label=label, widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))


class CustomUserCreationForm(StyledFormMixin, UserCreationForm):
    """Nouvel employé, rattaché à une boutique du compte (le compte n'a qu'un gérant)."""

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'shop')
        labels = {'username': "Identifiant de connexion", 'first_name': 'Prénom', 'last_name': 'Nom',
                  'email': 'Email', 'phone': 'Téléphone', 'shop': 'Boutique'}
        help_texts = {'username': '', 'email': 'Sert à récupérer le mot de passe oublié.',
                      'shop': "L'employé ne voit que cette boutique et arrive directement sur sa caisse."}

    def __init__(self, *args, scope=None, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        self.scope = scope
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['password1'].help_text = '8 caractères minimum.'
        self.fields['password2'].help_text = ''
        if 'shop' in self.fields:
            _shop_field(self.fields['shop'], scope)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Un utilisateur avec cet email existe déjà.')
        return email

    def clean_phone(self):
        phone = ''.join(ch for ch in (self.cleaned_data.get('phone') or '') if ch.isdigit())
        if phone and len(phone) < 7:
            raise ValidationError('Le numéro doit contenir au moins 7 chiffres.')
        return phone or None

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.request_user:
            user.created_by = self.request_user
        if self.scope:
            user.account = self.scope.account
            user.role = 'employee'
        if commit:
            user.save()
        return user


def _shop_field(field, scope):
    """Liste des boutiques du compte ; obligatoire pour un employé."""
    field.required = True
    field.empty_label = None
    field.queryset = scope.account.shops.filter(is_active=True) if scope else field.queryset.none()
    if scope and scope.shop and not field.initial:
        field.initial = scope.shop.pk


class CustomUserChangeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'shop', 'is_active')
        labels = {'username': "Identifiant de connexion", 'first_name': 'Prénom', 'last_name': 'Nom',
                  'email': 'Email', 'phone': 'Téléphone', 'shop': 'Boutique', 'is_active': 'Compte actif'}
        help_texts = {'username': ''}

    def __init__(self, *args, scope=None, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        if self.instance.role == 'manager':
            # Le gérant voit toutes les boutiques ; il ne peut pas se désactiver lui-même.
            del self.fields['shop']
            if self.request_user and self.request_user.pk == self.instance.pk:
                self.fields['is_active'].disabled = True
        else:
            _shop_field(self.fields['shop'], scope)

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise ValidationError('Un utilisateur avec cet email existe déjà.')
        return email


class PasswordChangeForm(StyledFormMixin, forms.Form):
    current_password = forms.CharField(label='Mot de passe actuel',
                                       widget=forms.PasswordInput(attrs={'autocomplete': 'current-password'}))
    new_password1 = _password_field('Nouveau mot de passe')
    new_password2 = _password_field('Confirmer le nouveau mot de passe')

    def clean(self):
        return _validate_new_password_pair(super().clean())


class ManagerResetPasswordForm(StyledFormMixin, forms.Form):
    new_password1 = _password_field('Nouveau mot de passe')
    new_password2 = _password_field('Confirmer le nouveau mot de passe')

    def clean(self):
        return _validate_new_password_pair(super().clean())


class ForgotRequestForm(StyledFormMixin, forms.Form):
    identifier = forms.CharField(label="Identifiant ou email",
                                 widget=forms.TextInput(attrs={'autofocus': True}))


class ForgotCodeForm(StyledFormMixin, forms.Form):
    code = forms.CharField(label='Code reçu par email', max_length=6,
                           widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code',
                                                         'placeholder': '6 chiffres'}))
    new_password1 = _password_field('Nouveau mot de passe')
    new_password2 = _password_field('Confirmer le nouveau mot de passe')

    def clean(self):
        return _validate_new_password_pair(super().clean())


class AppSettingForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AppSetting
        fields = ['company_name', 'company_tagline', 'low_stock_threshold',
                  'company_logo', 'brand_color_primary', 'brand_color_secondary', 'brand_color_accent',
                  'signatory_name', 'signature_image', 'stamp_image']
        labels = {
            'company_name': "Nom de l'entreprise",
            'company_tagline': 'Activité / slogan',
            'low_stock_threshold': "Seuil d'alerte stock",
            'company_logo': 'Logo',
            'brand_color_primary': 'Couleur principale',
            'brand_color_secondary': 'Couleur secondaire',
            'brand_color_accent': "Couleur d'accent",
            'signatory_name': 'Nom du signataire',
            'signature_image': 'Signature',
            'stamp_image': 'Cachet',
        }
        widgets = {
            'brand_color_primary': forms.TextInput(attrs={'type': 'color'}),
            'brand_color_secondary': forms.TextInput(attrs={'type': 'color'}),
            'brand_color_accent': forms.TextInput(attrs={'type': 'color'}),
            'company_logo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'signature_image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'stamp_image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }
        help_texts = {
            'brand_color_primary': 'Titres, bandeaux et tableau de la facture.',
            'brand_color_secondary': 'Montant payé et mention « payée ».',
            'brand_color_accent': 'Reste à payer et mention « impayée ».',
        }

    def clean(self):
        data = super().clean()
        for name in ('brand_color_primary', 'brand_color_secondary', 'brand_color_accent'):
            value = (data.get(name) or '').strip().lower()
            if value and not re.fullmatch(r'#[0-9a-f]{6}', value):
                self.add_error(name, 'Couleur invalide (format #RRGGBB).')
            elif value:
                data[name] = value
        return data
