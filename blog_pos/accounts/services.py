import calendar
import datetime

from django.db import transaction
from django.utils import timezone


def add_months(day, months):
    """5 janvier + 1 mois → 5 février ; 31 janvier + 1 mois → 28/29 février."""
    month = day.month - 1 + months
    year = day.year + month // 12
    month = month % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, calendar.monthrange(year, month)[1]))


def extend(account, months):
    """Active le compte pour `months` mois de plus.

    Encore ouvert : on prolonge à partir de sa date de fin (le client ne perd aucun jour).
    En attente, suspendu ou expiré : on repart d'aujourd'hui.
    """
    today = timezone.localdate()
    start = account.active_until if account.is_open and account.active_until else today - datetime.timedelta(days=1)
    account.active_until = add_months(start, months)
    account.is_active = True
    account.save(update_fields=['active_until', 'is_active'])
    return account.active_until


@transaction.atomic
def delete_account(account):
    """Supprime un compte client et TOUTES ses données (ventes, stock, clients, utilisateurs).

    Ordre imposé par les protections entre tables : on vide d'abord ce qui référence le reste.
    """
    from aprovision.models import Depense, MouvementStock, TypeDepense
    from client.models import Client
    from order.models import Order
    from product.models import Category, Product, Stock
    from users.models import AppSetting, User

    shops = account.shops.all()
    MouvementStock.objects.filter(shop__in=shops).delete()
    Order.objects.filter(shop__in=shops).delete()          # lignes et paiements suivent
    Client.objects.filter(shop__in=shops).delete()
    Depense.objects.filter(account=account).delete()
    TypeDepense.objects.filter(account=account).delete()
    Stock.objects.filter(shop__in=shops).delete()
    Product.objects.filter(account=account).delete()
    Category.objects.filter(account=account).delete()
    User.objects.filter(account=account).delete()
    AppSetting.objects.filter(account=account).delete()
    shops.delete()
    account.delete()
