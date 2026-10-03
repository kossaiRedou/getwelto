from decimal import Decimal

from django import forms


class ImageInput(forms.ClearableFileInput):
    """Champ image avec aperçu de l'image actuelle."""
    template_name = 'core/widgets/image_input.html'


class StyledFormMixin:
    """Applique les styles de l'app aux widgets, et la devise aux champs de montant."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        currency = None
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'checkbox'
            elif isinstance(widget, forms.ClearableFileInput):
                if type(widget) is forms.ClearableFileInput:
                    widget.template_name = ImageInput.template_name
                css = 'file-input'
            else:
                css = 'input'
            widget.attrs['class'] = css
            if isinstance(field, forms.DecimalField):
                if currency is None:
                    from users.models import AppSetting
                    currency = AppSetting.get_currency_label()
                field.suffix = currency
        if not self.is_bound:
            # « 25000.00 » s'affiche « 25000 » : plus lisible pour des francs sans centimes.
            for name, field in self.fields.items():
                value = self.initial.get(name, field.initial)
                if isinstance(field, forms.DecimalField) and isinstance(value, Decimal) \
                        and value == value.to_integral_value():
                    self.initial[name] = int(value)
