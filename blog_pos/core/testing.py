"""Outils communs aux tests : un compte client prêt à l'emploi."""
from accounts.models import Account, Shop
from product.models import Stock
from users.models import AppSetting, User

PASSWORD = 'motdepasse123'


def make_account(name='Boutique Test', shops=('Kaloum',), currency='GNF', country='GN', **extra):
    """Compte actif + ses boutiques + son gérant. Renvoie (compte, [boutiques], gérant)."""
    extra.setdefault('max_shops', max(len(shops), 1))
    account = Account.objects.create(name=name, country=country, currency=currency, is_active=True, **extra)
    AppSetting.objects.create(account=account, company_name=name)
    shop_objs = [Shop.objects.create(account=account, name=shop_name) for shop_name in shops]
    manager = User.objects.create_user(f'chef{account.pk}', password=PASSWORD, role='manager', account=account,
                                       first_name='Chef')
    return account, shop_objs, manager


def make_employee(shop, username, **extra):
    return User.objects.create_user(username, password=PASSWORD, role='employee', account=shop.account,
                                    shop=shop, **extra)


def stock_qty(shop, product):
    return Stock.objects.filter(shop=shop, product=product).values_list('qty', flat=True).first() or 0
