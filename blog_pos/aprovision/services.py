"""
Mouvements de stock WELTO.

`move_stock` est l'unique point d'écriture du stock d'un produit : elle applique
la variation avec une mise à jour conditionnelle (jamais de stock négatif, même
en cas d'accès concurrent) et journalise le mouvement avec les stocks avant/après
réels. Elle doit être appelée dans une transaction.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from product.models import Product
from .models import Depense, MouvementStock, TypeDepense, TypeMouvement


class StockError(Exception):
    pass


def move_stock(product_id, delta, type_mouvement, *, user=None, description='',
               order=None, depense=None, unit_cost=None):
    if delta == 0:
        raise StockError("La quantité du mouvement ne peut pas être nulle.")
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("move_stock doit être appelée dans transaction.atomic()")

    product = Product.objects.select_for_update().get(pk=product_id)
    qs = Product.objects.filter(pk=product_id)
    if delta < 0:
        qs = qs.filter(qty__gte=-delta)
    # updated_at bouge à chaque mouvement : le catalogue de la caisse se rafraîchit (ETag).
    if qs.update(qty=F('qty') + delta, updated_at=timezone.now()) != 1:
        raise StockError(f'Stock insuffisant pour « {product.title} » : '
                         f'{product.qty} disponible(s), {-delta} demandé(s).')

    stock_avant = product.qty
    cout_total = None
    if unit_cost is not None:
        unit_cost = Decimal(unit_cost)
        cout_total = unit_cost * abs(delta)
    return MouvementStock.objects.create(
        produit_id=product_id,
        type_mouvement=type_mouvement,
        quantite=delta,
        stock_avant=stock_avant,
        stock_apres=stock_avant + delta,
        prix_achat_unitaire=unit_cost,
        cout_total=cout_total,
        reference_commande=order,
        reference_depense=depense,
        description=description[:200],
        created_by=user,
    )


def restock(product_id, quantity, unit_cost, *, user=None, fournisseur='', reference='', description=''):
    """Approvisionnement : entrée de stock + dépense correspondante + mise à jour du prix d'achat."""
    if quantity <= 0:
        raise StockError("La quantité doit être supérieure à 0.")
    unit_cost = Decimal(unit_cost)
    if unit_cost < 0:
        raise StockError("Le prix d'achat ne peut pas être négatif.")
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product_id)
        depense = None
        if unit_cost > 0:
            type_appro, _ = TypeDepense.objects.get_or_create(
                nom='Approvisionnement',
                defaults={'description': 'Achat de marchandises pour le stock', 'couleur': '#16a34a'},
            )
            depense = Depense.objects.create(
                type_depense=type_appro,
                description=(description or f'Approvisionnement {product.title} × {quantity}')[:200],
                montant=unit_cost * quantity,
                fournisseur=fournisseur,
                reference=reference,
                created_by=user,
            )
            Product.objects.filter(pk=product_id).update(prix_achat=unit_cost, updated_at=timezone.now())
        return move_stock(product_id, quantity, TypeMouvement.ENTREE, user=user, depense=depense,
                          unit_cost=unit_cost if unit_cost > 0 else None,
                          description=description or f'Approvisionnement de {quantity} unité(s)')


def adjust_stock(product_id, action, quantity, *, user=None, description=''):
    """Ajustement manuel : 'add' (+n), 'remove' (−n, ex. perte/casse) ou 'set' (stock = n)."""
    if quantity < 0:
        raise StockError("La quantité ne peut pas être négative.")
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product_id)
        if action == 'add':
            delta, kind = quantity, TypeMouvement.AJUSTEMENT_PLUS
        elif action == 'remove':
            delta, kind = -quantity, TypeMouvement.SORTIE_PERTE
        elif action == 'set':
            delta = quantity - product.qty
            kind = TypeMouvement.AJUSTEMENT_PLUS if delta > 0 else TypeMouvement.AJUSTEMENT_MOINS
        else:
            raise StockError("Action inconnue.")
        if delta == 0:
            return None
        return move_stock(product_id, delta, kind, user=user,
                          description=description or f'Ajustement manuel ({delta:+d})')
