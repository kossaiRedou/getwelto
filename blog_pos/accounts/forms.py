import re

from django import forms
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

from core.forms import StyledFormMixin
from users.models import AppSetting, User
from .models import COUNTRY_CHOICES, CURRENCY_BY_COUNTRY, Account, Shop


class SignupForm(StyledFormMixin, forms.Form):
    """Inscription publique : le compte reste bloqué tant que le propriétaire du SaaS ne l'a pas activé."""
    company_name = forms.CharField(label="Nom de l'entreprise", max_length=150,
                                   widget=forms.TextInput(attrs={'autofocus': True}))
    country = forms.ChoiceField(label='Pays', choices=COUNTRY_CHOICES, initial='GN',
                                help_text='La devise suit le pays : un compte par pays.')
    shop_name = forms.CharField(label='Nom de votre première boutique', max_length=150, required=False,
                                help_text="Facultatif : par défaut, le nom de l'entreprise.")
    first_name = forms.CharField(label='Prénom', max_length=150)
    last_name = forms.CharField(label='Nom', max_length=150, required=False)
    phone = forms.CharField(label='Téléphone (WhatsApp)', max_length=30,
                            widget=forms.TextInput(attrs={'inputmode': 'tel', 'autocomplete': 'tel'}),
                            help_text='Pour vous contacter et activer votre compte.')
    email = forms.EmailField(label='Email', required=False,
                             help_text='Facultatif : sert à récupérer le mot de passe oublié.')
    username = forms.CharField(label='Identifiant de connexion', max_length=150,
                               widget=forms.TextInput(attrs={'autocapitalize': 'none', 'autocomplete': 'username'}))
    password1 = forms.CharField(label='Mot de passe', help_text='8 caractères minimum.',
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    password2 = forms.CharField(label='Confirmer le mot de passe',
                                widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}))
    # Piège à robots : champ invisible qu'un humain laisse vide.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if not re.fullmatch(r'[\w.@+-]+', username):
            raise forms.ValidationError('Lettres, chiffres et . @ + - _ uniquement, sans espace.')
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Cet identifiant est déjà pris.')
        return username

    def clean_phone(self):
        phone = ''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch == '+')
        if len(phone.lstrip('+')) < 7:
            raise forms.ValidationError('Numéro invalide.')
        return phone

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Un compte utilise déjà cet email.')
        return email

    def clean(self):
        data = super().clean()
        p1, p2 = data.get('password1'), data.get('password2')
        if p1 and p2:
            if p1 != p2:
                self.add_error('password2', 'Les mots de passe ne correspondent pas.')
            else:
                try:
                    validate_password(p1, User(username=data.get('username', ''), first_name=data.get('first_name', '')))
                except forms.ValidationError as exc:
                    self.add_error('password1', exc)
        return data

    @property
    def is_bot(self):
        return bool(self.cleaned_data.get('website'))

    @transaction.atomic
    def save(self):
        d = self.cleaned_data
        account = Account.objects.create(
            name=d['company_name'], country=d['country'], currency=CURRENCY_BY_COUNTRY[d['country']],
            phone=d['phone'], email=d['email'], is_active=False, max_shops=1)
        AppSetting.objects.create(account=account, company_name=d['company_name'])
        shop = Shop.objects.create(account=account, name=d['shop_name'] or d['company_name'], phone=d['phone'])
        user = User(username=d['username'], first_name=d['first_name'], last_name=d['last_name'],
                    email=d['email'], phone=d['phone'][:15], role='manager', account=account)
        user.set_password(d['password1'])
        user.save()
        return account, shop, user


class ShopForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Shop
        fields = ['name', 'code', 'address', 'phone']
        labels = {'name': 'Nom de la boutique', 'code': 'Code', 'address': 'Adresse', 'phone': 'Téléphone'}
        help_texts = {'code': 'Début des numéros de vente (ex : KAL-000123). Vide : choisi tout seul.',
                      'address': 'Imprimée sur les tickets et les factures de cette boutique.'}
        widgets = {'name': forms.TextInput(attrs={'placeholder': 'Ex : Boutique Kaloum', 'autofocus': True}),
                   'code': forms.TextInput(attrs={'autocapitalize': 'characters', 'maxlength': 6})}

    def __init__(self, *args, account, **kwargs):
        super().__init__(*args, **kwargs)
        self.account = account
        if not self.instance.pk:
            self.instance.account = account
        self.fields['code'].required = False

    def clean_name(self):
        name = ' '.join(self.cleaned_data['name'].split())
        if Shop.objects.filter(account=self.account, name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Vous avez déjà une boutique de ce nom.')
        return name

    def clean_code(self):
        code = (self.cleaned_data.get('code') or '').strip().upper()
        if not code:
            return ''
        if not re.fullmatch(r'[A-Z0-9]{2,6}', code):
            raise forms.ValidationError('2 à 6 lettres ou chiffres, sans espace.')
        if Shop.objects.filter(account=self.account, code=code).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('Ce code est déjà utilisé par une autre boutique.')
        return code
