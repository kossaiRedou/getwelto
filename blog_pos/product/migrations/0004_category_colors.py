"""Couleurs des catégories et des produits, catégorie par défaut « Autres »."""
import django.core.validators
import django.db.models.deletion
from django.db import migrations, models

PALETTE = ['#2563eb', '#16a34a', '#dc2626', '#ea580c', '#7c3aed', '#0891b2',
           '#db2777', '#ca8a04', '#0d9488', '#9333ea', '#65a30d', '#92400e']
HEX = django.core.validators.RegexValidator('^#[0-9a-f]{6}$', 'Couleur invalide.')


def forwards(apps, schema_editor):
    Category = apps.get_model('product', 'Category')
    Product = apps.get_model('product', 'Product')
    default, _ = Category.objects.get_or_create(title='Autres', defaults={'color': '#64748b'})
    Category.objects.filter(is_default=True).exclude(pk=default.pk).update(is_default=False)
    Category.objects.filter(pk=default.pk).update(is_default=True, color=default.color or '#64748b')
    for index, category in enumerate(Category.objects.exclude(pk=default.pk).filter(color='').order_by('title')):
        category.color = PALETTE[index % len(PALETTE)]
        category.save(update_fields=['color'])
    Product.objects.filter(category__isnull=True).update(category=default)


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0003_alter_category_options_alter_product_options_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='color',
            field=models.CharField(blank=True, help_text='Couleur des produits de la catégorie à la caisse',
                                   max_length=7, validators=[HEX]),
        ),
        migrations.AddField(
            model_name='category',
            name='is_default',
            field=models.BooleanField(default=False, editable=False,
                                      help_text='Catégorie « Autres » : celle des produits sans catégorie'),
        ),
        migrations.AddField(
            model_name='product',
            name='color',
            field=models.CharField(blank=True, help_text='Vide : couleur de la catégorie', max_length=7,
                                   validators=[HEX]),
        ),
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='product',
            name='category',
            field=models.ForeignKey(blank=True, help_text="« Autres » si aucune catégorie n'est choisie",
                                    on_delete=django.db.models.deletion.PROTECT, to='product.category'),
        ),
        migrations.AlterModelOptions(
            name='category',
            options={'ordering': ['-is_default', 'title'], 'verbose_name_plural': 'Categories'},
        ),
        migrations.AddConstraint(
            model_name='category',
            constraint=models.UniqueConstraint(condition=models.Q(('is_default', True)), fields=('is_default',),
                                               name='category_single_default'),
        ),
    ]
