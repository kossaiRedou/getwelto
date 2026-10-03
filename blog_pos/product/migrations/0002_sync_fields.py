"""
Ajout des champs de synchronisation (sync_uuid + updated_at).

Migration en 3 temps requise pour un champ unique à valeur générée :
1. ajout nullable, 2. backfill d'un uuid distinct par ligne, 3. contrainte unique.
"""
import uuid

from django.db import migrations, models


def backfill_sync_uuid(apps, schema_editor):
    for model_name in ('Category', 'Product'):
        Model = apps.get_model('product', model_name)
        for pk in Model.objects.values_list('pk', flat=True):
            Model.objects.filter(pk=pk).update(sync_uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('product', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='category',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='category',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='product',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(backfill_sync_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='category',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='product',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
