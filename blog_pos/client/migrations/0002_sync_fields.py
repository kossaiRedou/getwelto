"""Ajout du champ de synchronisation sync_uuid (Client a déjà updated_at)."""
import uuid

from django.db import migrations, models


def backfill_sync_uuid(apps, schema_editor):
    Client = apps.get_model('client', 'Client')
    for pk in Client.objects.values_list('pk', flat=True):
        Client.objects.filter(pk=pk).update(sync_uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('client', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(backfill_sync_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='client',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
