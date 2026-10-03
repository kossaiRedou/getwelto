from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ValidationError

from core.forms import StyledFormMixin
from .models import AppSetting, User

CURRENCIES = [('GNF', 'GNF — Franc guinéen'), ('GMD', 'GMD — Dalasi gambien'),
              ('XOF', 'XOF — Franc CFA'), ('SLE', 'SLE — Leone'), ('EUR', 'EUR — Euro')]


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
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'role')
        labels = {'username': "Identifiant de connexion", 'first_name': 'Prénom', 'last_name': 'Nom',
                  'email': 'Email', 'phone': 'Téléphone', 'role': 'Rôle'}
        help_texts = {'username': '', 'email': 'Sert à récupérer le mot de passe oublié.'}

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        self.fields['first_name'].required = True
        self.fields['password1'].help_text = '8 caractères minimum.'
        self.fields['password2'].help_text = ''

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
        if commit:
            user.save()
        return user


class SetupForm(CustomUserCreationForm):
    """Premier lancement : compte manager + identité de la boutique."""
    company_name = forms.CharField(label='Nom de la boutique', max_length=150)
    currency_label = forms.ChoiceField(label='Devise', choices=CURRENCIES, initial='GNF')

    class Meta(CustomUserCreationForm.Meta):
        fields = ('username', 'first_name', 'last_name', 'email', 'phone')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(['company_name', 'currency_label', 'first_name', 'last_name', 'username',
                           'email', 'phone', 'password1', 'password2'])


class CustomUserChangeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'role', 'is_active')
        labels = {'username': "Identifiant de connexion", 'first_name': 'Prénom', 'last_name': 'Nom',
                  'email': 'Email', 'phone': 'Téléphone', 'role': 'Rôle', 'is_active': 'Compte actif'}
        help_texts = {'username': ''}

    def __init__(self, *args, **kwargs):
        self.request_user = kwargs.pop('request_user', None)
        super().__init__(*args, **kwargs)
        if self.request_user and self.request_user.pk == self.instance.pk:
            # Un manager ne peut pas se rétrograder ni se désactiver lui-même.
            self.fields['role'].disabled = True
            self.fields['is_active'].disabled = True

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
        fields = ['company_name', 'company_tagline', 'currency_label', 'low_stock_threshold',
                  'company_logo', 'brand_color_primary', 'signatory_name', 'signature_image', 'stamp_image']
        labels = {
            'company_name': 'Nom de la boutique',
            'company_tagline': 'Activité / slogan',
            'currency_label': 'Devise',
            'low_stock_threshold': "Seuil d'alerte stock",
            'company_logo': 'Logo',
            'brand_color_primary': 'Couleur des factures',
            'signatory_name': 'Nom du signataire',
            'signature_image': 'Signature',
            'stamp_image': 'Cachet',
        }
        widgets = {
            'brand_color_primary': forms.TextInput(attrs={'type': 'color'}),
            'company_logo': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'signature_image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
            'stamp_image': forms.ClearableFileInput(attrs={'accept': 'image/*'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['brand_color_primary'].widget.attrs['class'] = 'h-11 w-20 cursor-pointer rounded-lg border border-slate-300 bg-white p-1'
