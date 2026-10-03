"""Ajout des champs de synchronisation sur TypeDepense, Depense, MouvementStock."""
import uuid

from django.db import migrations, models


def backfill_sync_uuid(apps, schema_editor):
    for model_name in ('TypeDepense', 'Depense', 'MouvementStock'):
        Model = apps.get_model('aprovision', model_name)
        for pk in Model.objects.values_list('pk', flat=True):
            Model.objects.filter(pk=pk).update(sync_uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('aprovision', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='typedepense',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='typedepense',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='depense',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='depense',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='mouvementstock',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='mouvementstock',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(backfill_sync_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='typedepense',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='depense',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='mouvementstock',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
