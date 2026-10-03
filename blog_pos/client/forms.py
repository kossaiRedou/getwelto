from django import forms

from core.forms import StyledFormMixin
from .models import Client, normalize_phone


def clean_phone_value(raw, instance_pk=None):
    phone = normalize_phone(raw)
    digits = phone.lstrip('+')
    if not 7 <= len(digits) <= 15:
        raise forms.ValidationError('Numéro invalide : 7 à 15 chiffres.')
    existing = Client.objects.filter(phone=phone)
    if instance_pk:
        existing = existing.exclude(pk=instance_pk)
    if existing.exists():
        raise forms.ValidationError(f'Un client avec le numéro {phone} existe déjà.')
    return phone


def clean_name_value(raw):
    name = ' '.join((raw or '').split())
    if len(name) < 2:
        raise forms.ValidationError('Le nom doit contenir au moins 2 caractères.')
    return name


class ClientForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'phone', 'is_active']
        labels = {'name': 'Nom', 'phone': 'Téléphone', 'is_active': 'Client actif'}
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'Nom du client', 'autofocus': True}),
            'phone': forms.TextInput(attrs={'placeholder': 'Ex : 622 12 34 56', 'inputmode': 'tel'}),
        }

    def clean_phone(self):
        return clean_phone_value(self.cleaned_data.get('phone'), self.instance.pk)

    def clean_name(self):
        return clean_name_value(self.cleaned_data.get('name'))
