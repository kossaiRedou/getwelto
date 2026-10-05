"""
Cloisonnement des données entre comptes et boutiques.

Chaque requête porte un `Scope` (request.scope) : le compte de l'utilisateur et
la boutique concernée. Les vues ne lisent JAMAIS un modèle métier directement :
elles passent par le scope, qui filtre sur le compte et, si une boutique est
choisie, sur cette boutique.

- Employé : toujours sa boutique, rien d'autre.
- Gérant : une boutique choisie, ou « Toutes les boutiques » (shop = None).

Le compte courant est aussi publié dans une variable de contexte, pour les
quelques endroits sans requête (devise d'un formulaire, __str__ d'un modèle).
"""
from contextvars import ContextVar

from django.db.models import Count, IntegerField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce

_current_account = ContextVar('welto_account', default=None)


def current_account():
    return _current_account.get()


def activate(account):
    """Publie le compte courant ; renvoie le jeton à passer à deactivate()."""
    return _current_account.set(account)


def deactivate(token):
    _current_account.reset(token)


class Scope:
    def __init__(self, user, account, shop, shops):
        self.user = user
        self.account = account
        self.shop = shop                 # None = toutes les boutiques (gérant)
        self.shops = shops               # boutiques actives visibles par l'utilisateur
        self.is_manager = getattr(user, 'role', None) == 'manager'

    # ------------------------------------------------------------ boutiques
    @property
    def all_shops(self):
        return self.shop is None

    @property
    def multi_shop(self):
        """Le gérant a plusieurs boutiques : sélecteur et vue d'ensemble."""
        return self.is_manager and len(self.shops) > 1

    def shop_ids(self):
        return [self.shop.pk] if self.shop else [s.pk for s in self.shops]

    def get_shop(self, pk):
        """Boutique du compte (active), ou None."""
        return next((s for s in self.shops if str(s.pk) == str(pk)), None)

    # ------------------------------------------------------------ catalogue (commun au compte)
    def products(self):
        from product.models import Product
        return Product.objects.filter(account=self.account)

    def categories(self):
        from product.models import Category
        return Category.objects.filter(account=self.account)

    def default_category(self):
        from product.models import Category
        return Category.get_default(self.account)

    def products_with_qty(self):
        """Produits annotés de `qty` : stock de la boutique, ou total des boutiques actives."""
        from product.models import Stock
        stocks = Stock.objects.filter(product=OuterRef('pk'), shop_id__in=self.shop_ids())
        total = stocks.values('product').annotate(s=Sum('qty')).values('s')[:1]
        return self.products().annotate(qty=Coalesce(Subquery(total, output_field=IntegerField()), Value(0)))

    def low_stock(self, products, threshold):
        """Produits sous le seuil dans la boutique — ou dans au moins une boutique (vue d'ensemble)."""
        from product.models import Stock
        if self.shop:
            return products.filter(qty__lt=threshold)
        ok = (Stock.objects.filter(product=OuterRef('pk'), shop_id__in=self.shop_ids(), qty__gte=threshold)
              .values('product').annotate(n=Count('pk')).values('n')[:1])
        return (products.annotate(ok_shops=Coalesce(Subquery(ok, output_field=IntegerField()), Value(0)))
                .filter(ok_shops__lt=len(self.shop_ids())))

    def stock_by_shop(self, product_ids):
        """{product_id: [(boutique, qty), …]} pour les boutiques visibles (0 si jamais approvisionné)."""
        from product.models import Stock
        rows = {(s, p): q for s, p, q in Stock.objects.filter(product_id__in=product_ids, shop_id__in=self.shop_ids())
                .values_list('shop_id', 'product_id', 'qty')}
        shops = [self.shop] if self.shop else self.shops
        return {pid: [(shop, rows.get((shop.pk, pid), 0)) for shop in shops] for pid in product_ids}

    # ------------------------------------------------------------ données de boutique
    def _by_shop(self, qs, field='shop'):
        qs = qs.filter(**{f'{field}__account': self.account})
        if self.shop:
            qs = qs.filter(**{field: self.shop})
        return qs

    def _reachable(self, qs, field='shop'):
        """Accès à un objet précis : tout le compte pour le gérant, sa boutique pour l'employé."""
        qs = qs.filter(**{f'{field}__account': self.account})
        if not self.is_manager:
            qs = qs.filter(**{field: self.shop})
        return qs

    def orders(self):
        from order.models import Order
        return self._by_shop(Order.objects.all())

    def reachable_orders(self):
        from order.models import Order
        return self._reachable(Order.objects.all())

    def payments(self):
        from order.models import Payment
        return self._by_shop(Payment.objects.all(), 'order__shop')

    def clients(self):
        from client.models import Client
        return self._by_shop(Client.objects.all())

    def reachable_clients(self):
        from client.models import Client
        return self._reachable(Client.objects.all())

    def movements(self):
        from aprovision.models import MouvementStock
        return self._by_shop(MouvementStock.objects.all())

    def expenses(self):
        """Dépenses : celles de la boutique choisie, ou toutes (communes comprises) en vue d'ensemble."""
        from aprovision.models import Depense
        qs = Depense.objects.filter(account=self.account)
        if self.shop:
            qs = qs.filter(shop=self.shop)
        return qs

    def expense_types(self):
        from aprovision.models import TypeDepense
        return TypeDepense.objects.filter(account=self.account)

    def users(self):
        from users.models import User
        return User.objects.filter(account=self.account)

    def settings(self):
        from users.models import AppSetting
        return AppSetting.for_account(self.account)

    def store_key(self):
        """Suffixe des données gardées dans le navigateur (catalogue, panier) : une boutique = un tiroir."""
        return f'{self.account.pk}-{self.shop.pk if self.shop else 0}'
