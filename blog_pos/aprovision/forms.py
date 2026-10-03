from decimal import Decimal

from django import forms

from core.forms import StyledFormMixin
from .models import Depense, TypeDepense


class DepenseForm(StyledFormMixin, forms.ModelForm):
    new_type = forms.CharField(label='Ou nouveau type', required=False, max_length=100,
                               widget=forms.TextInput(attrs={'placeholder': 'Ex : Loyer, Transport…'}))

    class Meta:
        model = Depense
        fields = ['type_depense', 'montant', 'date_depense', 'description', 'fournisseur', 'reference']
        labels = {
            'type_depense': 'Type de dépense',
            'montant': 'Montant',
            'date_depense': 'Date',
            'description': 'Description',
            'fournisseur': 'Bénéficiaire / fournisseur',
            'reference': 'Référence (facture…)',
        }
        widgets = {
            'montant': forms.NumberInput(attrs={'inputmode': 'decimal', 'step': '0.01', 'min': '0.01'}),
            'date_depense': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['type_depense'].queryset = TypeDepense.objects.filter(actif=True).exclude(nom='Approvisionnement')
        self.fields['type_depense'].required = False
        self.fields['type_depense'].empty_label = '— Choisir —'
        self.fields['fournisseur'].required = False
        self.fields['reference'].required = False

    def clean_montant(self):
        montant = self.cleaned_data.get('montant')
        if montant is not None and montant <= Decimal('0'):
            raise forms.ValidationError('Le montant doit être supérieur à 0.')
        return montant

    def clean(self):
        data = super().clean()
        new_type = ' '.join((data.get('new_type') or '').split())
        if new_type:
            data['type_depense'], _ = TypeDepense.objects.get_or_create(
                nom__iexact=new_type, defaults={'nom': new_type})
        elif not data.get('type_depense'):
            self.add_error('type_depense', 'Choisissez un type ou saisissez-en un nouveau.')
        return data

    def save(self, commit=True):
        self.instance.type_depense = self.cleaned_data['type_depense']
        return super().save(commit)
