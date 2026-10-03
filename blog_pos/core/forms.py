from django import forms


class StyledFormMixin:
    """Applique les classes Tailwind de l'app aux widgets (input, select, checkbox…)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = 'checkbox'
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = 'input'
            elif isinstance(widget, forms.ClearableFileInput):
                css = 'file-input'
            else:
                css = 'input'
            widget.attrs['class'] = css
