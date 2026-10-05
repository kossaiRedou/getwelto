"""Passage au SaaS : les données d'avant (une seule boutique) deviennent le premier compte client.

Rien n'est supprimé. S'il n'y a aucune donnée, aucun compte n'est créé. Le
propriétaire du SaaS peut ensuite supprimer ce compte depuis l'admin s'il veut
repartir de zéro.
"""
import re
import unicodedata

from django.db import migrations

COUNTRY_BY_CURRENCY = {'GNF': 'GN', 'GMD': 'GM', 'XOF': 'SN', 'SLE': 'SL'}


def _code(name):
    ascii_name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    return (re.sub(r'[^A-Za-z]', '', ascii_name).upper()[:3] or 'BTQ').ljust(3, 'X')


def forwards(apps, schema_editor):
    Account = apps.get_model('accounts', 'Account')
    Shop = apps.get_model('accounts', 'Shop')
    User = apps.get_model('users', 'User')
    AppSetting = apps.get_model('users', 'AppSetting')
    Category = apps.get_model('product', 'Category')
    Product = apps.get_model('product', 'Product')
    Stock = apps.get_model('product', 'Stock')
    Client = apps.get_model('client', 'Client')
    Order = apps.get_model('order', 'Order')
    TypeDepense = apps.get_model('aprovision', 'TypeDepense')
    Depense = apps.get_model('aprovision', 'Depense')
    MouvementStock = apps.get_model('aprovision', 'MouvementStock')

    # Le propriétaire du SaaS (superutilisateur créé en ligne de commande) reste sans compte.
    # Le gérant créé par l'ancien premier lancement était aussi superutilisateur : il suit ses données.
    users = User.objects.exclude(is_superuser=True, role='employee').filter(account__isnull=True)
    # Catégorie « Autres » et type « Approvisionnement » sont créés d'office : ce ne sont pas des données.
    business = [Product, Client, Order, Depense, MouvementStock]
    if not users.exists() and not any(m.objects.exists() for m in business):
        # Base sans données : on retire ces valeurs par défaut orphelines (chaque compte crée les siennes).
        AppSetting.objects.filter(account__isnull=True).delete()
        Category.objects.filter(account__isnull=True).delete()
        TypeDepense.objects.filter(account__isnull=True).delete()
        return

    setting = AppSetting.objects.filter(account__isnull=True).order_by('pk').first()
    currency = (setting.currency_label if setting else '') or 'GNF'
    name = (setting.company_name if setting else '') or 'Mon entreprise'
    account = Account.objects.create(name=name, country=COUNTRY_BY_CURRENCY.get(currency, 'GN'),
                                     currency=currency, is_active=True, max_shops=1,
                                     admin_notes='Créé automatiquement au passage au SaaS (données d\'avant).')
    shop = Shop.objects.create(account=account, name=name, code=_code(name))

    if setting:
        AppSetting.objects.filter(pk=setting.pk).update(account=account)
    AppSetting.objects.filter(account__isnull=True).delete()          # doublons éventuels

    Category.objects.filter(account__isnull=True).update(account=account)
    Product.objects.filter(account__isnull=True).update(account=account)
    TypeDepense.objects.filter(account__isnull=True).update(account=account)
    Depense.objects.filter(account__isnull=True).update(account=account, shop=shop)
    Client.objects.filter(shop__isnull=True).update(shop=shop)
    Order.objects.filter(shop__isnull=True).update(shop=shop)
    MouvementStock.objects.filter(shop__isnull=True).update(shop=shop)
    Stock.objects.bulk_create([Stock(shop=shop, product_id=pk, qty=qty)
                               for pk, qty in Product.objects.filter(qty__gt=0).values_list('pk', 'qty')])

    # Un seul gérant par compte : le premier garde ce rôle, les autres deviennent employés.
    managers = list(users.filter(role='manager').order_by('pk'))
    if managers:
        User.objects.filter(pk=managers[0].pk).update(account=account, shop=None)
    users.exclude(pk=managers[0].pk if managers else None).update(account=account, shop=shop, role='employee')


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('users', '0006_saas_1'),
        ('product', '0005_saas_1'),
        ('client', '0004_saas_1'),
        ('order', '0006_saas_1'),
        ('aprovision', '0005_saas_1'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
