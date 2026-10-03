from decimal import Decimal

from django import forms

from core.forms import ColorSwatches, StyledFormMixin
from .models import COLOR_CHOICES, Category, Product

MONEY_ATTRS = {'inputmode': 'decimal', 'step': '0.01', 'min': '0'}


class ProductForm(StyledFormMixin, forms.ModelForm):
    initial_qty = forms.IntegerField(
        label='Stock initial', min_value=0, required=False,
        help_text="Quantité déjà en boutique (sans créer de dépense).",
        widget=forms.NumberInput(attrs={'inputmode': 'numeric', 'min': '0'}),
    )

    class Meta:
        model = Product
        fields = ['title', 'barcode', 'category', 'color', 'value', 'discount_value', 'prix_achat', 'active']
        labels = {
            'title': 'Nom du produit',
            'barcode': 'Code-barres',
            'category': 'Catégorie',
            'value': 'Prix de vente',
            'discount_value': 'Prix promo',
            'prix_achat': "Prix d'achat",
            'active': 'Produit en vente',
            'color': 'Couleur à la caisse',
        }
        help_texts = {
            'color': 'Par défaut, le produit prend la couleur de sa catégorie.',
            'barcode': 'Facultatif : scannez le code avec la douchette.',
            'discount_value': 'Facultatif : laissez vide s’il n’y a pas de promotion.',
            'prix_achat': 'Facultatif, mais nécessaire pour connaître votre marge.',
        }
        error_messages = {
            'title': {'unique': 'Un produit porte déjà ce nom.'},
            'barcode': {'unique': 'Ce code-barres est déjà attribué à un autre produit.'},
        }
        widgets = {
            'title': forms.TextInput(attrs={'placeholder': 'Ex : Riz 5 kg', 'autofocus': True}),
            'barcode': forms.TextInput(attrs={'autocomplete': 'off'}),
            'value': forms.NumberInput(attrs=MONEY_ATTRS),
            'discount_value': forms.NumberInput(attrs=MONEY_ATTRS),
            'prix_achat': forms.NumberInput(attrs=MONEY_ATTRS),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].empty_label = None
        self.fields['category'].required = False
        if not self.instance.pk and not self.initial.get('category'):
            self.initial['category'] = Category.get_default().pk
        self.fields['color'].widget = ColorSwatches(choices=[('', 'Comme la catégorie')] + COLOR_CHOICES)
        self.fields['barcode'].required = False
        for name in ('discount_value', 'prix_achat'):
            self.fields[name].required = False
            if not self.is_bound and not self.initial.get(name):
                self.initial[name] = None   # champ vide plutôt que « 0 »
        if self.instance.pk:
            del self.fields['initial_qty']

    def clean_discount_value(self):
        return self.cleaned_data.get('discount_value') or Decimal('0')

    def clean_prix_achat(self):
        return self.cleaned_data.get('prix_achat') or Decimal('0')

    def clean_color(self):
        color = self.cleaned_data.get('color') or ''
        if color and color not in dict(COLOR_CHOICES):
            raise forms.ValidationError('Couleur invalide.')
        return color

    def clean_barcode(self):
        return (self.cleaned_data.get('barcode') or '').strip() or None

    def clean(self):
        data = super().clean()
        value = data.get('value')
        promo = data.get('discount_value')
        for name in ('value', 'discount_value', 'prix_achat'):
            amount = data.get(name)
            if amount is not None and amount < 0:
                self.add_error(name, 'Le montant ne peut pas être négatif.')
        if value is not None and promo and promo >= value:
            self.add_error('discount_value', 'Le prix promo doit être inférieur au prix de vente.')
        return data


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ['title', 'color']
        labels = {'title': 'Nom', 'color': 'Couleur'}
        error_messages = {'title': {'unique': 'Cette catégorie existe déjà.'}}
        widgets = {'title': forms.TextInput(attrs={'placeholder': 'Ex : Boissons'}),
                   'color': ColorSwatches(choices=COLOR_CHOICES)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['color'].required = True
        if not self.instance.pk and not self.is_bound:
            self.initial['color'] = Category.next_color()


class StockForm(StyledFormMixin, forms.Form):
    ACTIONS = [
        ('restock', 'Approvisionnement (achat)'),
        ('add', 'Ajout (correction +)'),
        ('remove', 'Retrait (perte, casse)'),
        ('set', 'Inventaire (stock compté)'),
    ]
    action = forms.ChoiceField(label='Opération', choices=ACTIONS, initial='restock', widget=forms.RadioSelect)
    quantity = forms.IntegerField(label='Quantité', min_value=0,
                                  widget=forms.NumberInput(attrs={'inputmode': 'numeric', 'min': '0'}))
    unit_cost = forms.DecimalField(label="Prix d'achat unitaire", required=False, min_value=Decimal('0'),
                                   decimal_places=2, max_digits=14,
                                   widget=forms.NumberInput(attrs=MONEY_ATTRS))
    fournisseur = forms.CharField(label='Fournisseur', required=False, max_length=150)
    description = forms.CharField(label='Note', required=False, max_length=200)

    def clean(self):
        data = super().clean()
        action = data.get('action')
        qty = data.get('quantity')
        if action in ('restock', 'add', 'remove') and qty is not None and qty < 1:
            self.add_error('quantity', 'La quantité doit être au moins 1.')
        if action == 'restock' and data.get('unit_cost') is None:
            self.add_error('unit_cost', "Le prix d'achat est obligatoire pour un approvisionnement.")
        return data
