"""Ajout des champs de synchronisation (sync_uuid + updated_at) sur Order, OrderItem, Payment."""
import uuid

from django.db import migrations, models


def backfill_sync_uuid(apps, schema_editor):
    for model_name in ('Order', 'OrderItem', 'Payment'):
        Model = apps.get_model('order', model_name)
        for pk in Model.objects.values_list('pk', flat=True):
            Model.objects.filter(pk=pk).update(sync_uuid=uuid.uuid4())


class Migration(migrations.Migration):

    dependencies = [
        ('order', '0003_alter_payment_method'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='orderitem',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='sync_uuid',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.AddField(
            model_name='payment',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.RunPython(backfill_sync_uuid, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='order',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='orderitem',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
        migrations.AlterField(
            model_name='payment',
            name='sync_uuid',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
