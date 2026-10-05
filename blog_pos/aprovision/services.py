"""
Mouvements de stock WELTO.

`move_stock` est l'unique point d'écriture du stock d'un produit dans une
boutique : elle applique la variation avec une mise à jour conditionnelle
(jamais de stock négatif, même en cas d'accès concurrent) et journalise le
mouvement avec les stocks avant/après réels. Elle doit être appelée dans une
transaction. Le produit doit appartenir au compte de la boutique.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from core.utils import fix_scanned_code
from product.models import Product, Stock
from .models import Depense, MouvementStock, TypeDepense, TypeMouvement


class StockError(Exception):
    pass


def move_stock(product_id, delta, type_mouvement, *, shop, user=None, description='',
               order=None, depense=None, unit_cost=None, key=None):
    if delta == 0:
        raise StockError("La quantité du mouvement ne peut pas être nulle.")
    if not transaction.get_connection().in_atomic_block:
        raise RuntimeError("move_stock doit être appelée dans transaction.atomic()")

    # Le verrou sur le produit ordonne les mouvements concurrents de ce produit.
    product = Product.objects.select_for_update().get(pk=product_id)
    if product.account_id != shop.account_id:
        raise StockError("Ce produit n'appartient pas à cette boutique.")
    stock, _ = Stock.objects.select_for_update().get_or_create(shop=shop, product_id=product_id)
    qs = Stock.objects.filter(pk=stock.pk)
    if delta < 0:
        qs = qs.filter(qty__gte=-delta)
    if qs.update(qty=F('qty') + delta, updated_at=timezone.now()) != 1:
        raise StockError(f'Stock insuffisant pour « {product.title} » : '
                         f'{stock.qty} disponible(s), {-delta} demandé(s).')
    # updated_at du produit bouge aussi : le catalogue de la caisse se rafraîchit.
    Product.objects.filter(pk=product_id).update(updated_at=timezone.now())

    stock_avant = stock.qty
    cout_total = None
    if unit_cost is not None:
        unit_cost = Decimal(unit_cost)
        cout_total = unit_cost * abs(delta)
    extra = {'sync_uuid': key} if key else {}
    return MouvementStock.objects.create(
        **extra,
        shop=shop,
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


def restock(product_id, quantity, unit_cost, *, shop, user=None, fournisseur='', reference='', description=''):
    """Approvisionnement d'une boutique : entrée de stock + dépense de la boutique + prix d'achat mis à jour."""
    if quantity <= 0:
        raise StockError("La quantité doit être supérieure à 0.")
    unit_cost = Decimal(unit_cost)
    if unit_cost < 0:
        raise StockError("Le prix d'achat ne peut pas être négatif.")
    with transaction.atomic():
        product = Product.objects.select_for_update().get(pk=product_id)
        depense = None
        if unit_cost > 0:
            depense = Depense.objects.create(
                account_id=shop.account_id, shop=shop,
                type_depense=_type_appro(shop.account_id),
                description=(description or f'Approvisionnement {product.title} × {quantity}')[:200],
                montant=unit_cost * quantity,
                fournisseur=fournisseur,
                reference=reference,
                created_by=user,
            )
            Product.objects.filter(pk=product_id).update(prix_achat=unit_cost, updated_at=timezone.now())
        return move_stock(product_id, quantity, TypeMouvement.ENTREE, shop=shop, user=user, depense=depense,
                          unit_cost=unit_cost if unit_cost > 0 else None,
                          description=description or f'Approvisionnement de {quantity} unité(s)')


def adjust_stock(product_id, action, quantity, *, shop, user=None, description=''):
    """Ajustement manuel dans une boutique : 'add' (+n), 'remove' (−n, perte/casse) ou 'set' (stock = n)."""
    if quantity < 0:
        raise StockError("La quantité ne peut pas être négative.")
    with transaction.atomic():
        Product.objects.select_for_update().get(pk=product_id)
        current = Stock.objects.filter(shop=shop, product_id=product_id).values_list('qty', flat=True).first() or 0
        if action == 'add':
            delta, kind = quantity, TypeMouvement.AJUSTEMENT_PLUS
        elif action == 'remove':
            delta, kind = -quantity, TypeMouvement.SORTIE_PERTE
        elif action == 'set':
            delta = quantity - current
            kind = TypeMouvement.AJUSTEMENT_PLUS if delta > 0 else TypeMouvement.AJUSTEMENT_MOINS
        else:
            raise StockError("Action inconnue.")
        if delta == 0:
            return None
        return move_stock(product_id, delta, kind, shop=shop, user=user,
                          description=description or f'Ajustement manuel ({delta:+d})')


def _type_appro(account_id):
    type_appro, _ = TypeDepense.objects.get_or_create(
        account_id=account_id, nom='Approvisionnement',
        defaults={'description': 'Achat de marchandises pour le stock', 'couleur': '#16a34a'})
    return type_appro


def _parse_reception(lines):
    from order.services import SaleError, to_money, to_qty

    def money(value, label, required=False):
        try:
            amount = to_money(value, label)
        except SaleError as exc:
            raise StockError(exc.message)
        if amount is None and required:
            raise StockError(f'{label} obligatoire.')
        if amount is not None and amount < 0:
            raise StockError(f'{label} ne peut pas être négatif.')
        return amount

    if not lines:
        raise StockError('La réception est vide.')
    parsed, ids, titles, barcodes = [], set(), set(), set()
    for line in lines:
        try:
            qty = to_qty(line.get('qty'))
        except SaleError as exc:
            raise StockError(exc.message)
        item = {
            'qty': qty,
            'unit_cost': money(line.get('unit_cost'), "Prix d'achat", required=True),
            'price': money(line.get('price'), 'Prix de vente'),
            'barcode': fix_scanned_code(str(line.get('barcode') or '')) or None,
        }
        new = line.get('new')
        if new:
            title = ' '.join(str(new.get('title') or '').split())
            if len(title) < 2:
                raise StockError('Nom du nouveau produit trop court.')
            if title.lower() in titles:
                raise StockError(f'« {title} » apparaît deux fois dans la réception.')
            titles.add(title.lower())
            item['new'] = {'title': title, 'category_id': new.get('category_id') or None}
            item['price'] = money(new.get('price'), 'Prix de vente', required=True)
            if item['price'] <= 0:
                raise StockError(f'Prix de vente de « {title} » obligatoire.')
            item['barcode'] = fix_scanned_code(str(new.get('barcode') or '')) or None
        else:
            try:
                pid = int(line.get('product_id'))
            except (TypeError, ValueError):
                raise StockError('Produit invalide dans la réception.')
            if pid in ids:
                raise StockError('Un produit apparaît deux fois dans la réception.')
            ids.add(pid)
            item['product_id'] = pid
        if item['barcode']:
            if item['barcode'] in barcodes:
                raise StockError(f'Le code-barres {item["barcode"]} apparaît deux fois.')
            barcodes.add(item['barcode'])
        parsed.append(item)
    return parsed, ids


def receive(lines, *, user, shop, fournisseur='', reference='', key=None, can_set_price=True):
    """Réception de marchandises dans une boutique (page « Approvisionnement ») — tout ou rien.

    Chaque ligne : {'product_id': id} pour un produit existant, ou
    {'new': {'title', 'barcode', 'category_id', 'price'}} pour le créer, plus
    'qty' (reçue), 'unit_cost' (prix d'achat) et en option 'price' (nouveau prix
    de vente) et 'barcode' (code-barres à associer à un produit existant).
    Sans `can_set_price` (employé), le prix de vente d'un produit existant ne
    peut pas changer ; un nouveau produit reçoit toujours son prix.
    Une seule dépense « Approvisionnement » couvre tout le bon.
    `key` rend l'opération idempotente : renvoyée deux fois (réseau lent), elle
    n'est enregistrée qu'une fois — le second appel retourne None.
    """
    from django.db import IntegrityError
    from product.models import Category

    if key and MouvementStock.objects.filter(sync_uuid=key).exists():
        return None
    parsed, ids = _parse_reception(lines)
    fournisseur = (fournisseur or '').strip()
    reference = (reference or '').strip()

    catalog = Product.objects.filter(account_id=shop.account_id)
    try:
        with transaction.atomic():
            products = {p.pk: p for p in
                        catalog.select_for_update().filter(pk__in=ids).order_by('pk')}
            if len(products) != len(ids):
                raise StockError("Un produit de la réception n'existe plus. Rechargez la page.")

            for item in parsed:
                code = item['barcode']
                if code:
                    owner = catalog.filter(barcode=code).exclude(pk=item.get('product_id')).first()
                    if owner:
                        raise StockError(f'Le code-barres {code} appartient déjà à « {owner.title} ».')
                new = item.get('new')
                if new:
                    if catalog.filter(title__iexact=new['title']).exists():
                        raise StockError(f'Le produit « {new["title"]} » existe déjà : recherchez-le.')
                    category = None
                    if new['category_id']:
                        category = Category.objects.filter(pk=new['category_id'], account_id=shop.account_id).first()
                        if category is None:
                            raise StockError('Catégorie introuvable.')
                    product = Product.objects.create(account_id=shop.account_id, title=new['title'],
                                                     barcode=code, category=category,
                                                     value=item['price'], prix_achat=item['unit_cost'])
                    item['product_id'] = product.pk
                    item['created'] = True
                    continue

                product = products[item['product_id']]
                if item['price'] is not None and item['price'] != product.value:
                    if not can_set_price:
                        raise StockError(f'Seul le gérant peut changer le prix de vente de « {product.title} ».')
                    if item['price'] <= 0:
                        raise StockError(f'Prix de vente de « {product.title} » invalide.')
                    if product.discount_value and product.discount_value >= item['price']:
                        raise StockError(f'« {product.title} » a un prix promo supérieur au nouveau prix : '
                                         'modifiez la promo dans la fiche produit.')
                    product.value = item['price']
                if code:
                    product.barcode = code
                if item['unit_cost'] > 0:
                    product.prix_achat = item['unit_cost']
                product.save()

            total = sum((i['unit_cost'] * i['qty'] for i in parsed), Decimal('0'))
            depense = None
            if total > 0:
                n = len(parsed)
                depense = Depense.objects.create(
                    account_id=shop.account_id, shop=shop,
                    type_depense=_type_appro(shop.account_id), montant=total, created_by=user,
                    description=(f'Réception de {n} produit{"s" if n > 1 else ""}'
                                 + (f' — {fournisseur}' if fournisseur else ''))[:200],
                    fournisseur=fournisseur[:150], reference=reference[:50])
            label = 'Réception' + (f' {fournisseur}' if fournisseur else '')
            for index, item in enumerate(parsed):
                move_stock(item['product_id'], item['qty'], TypeMouvement.ENTREE, shop=shop, user=user,
                           depense=depense,
                           unit_cost=item['unit_cost'] if item['unit_cost'] > 0 else None,
                           key=key if index == 0 else None,
                           description=label + (' (nouveau produit)' if item.get('created') else ''))
    except IntegrityError:
        if key and MouvementStock.objects.filter(sync_uuid=key).exists():
            return None
        raise StockError('Conflit : un nom ou un code-barres est déjà utilisé. Rechargez la page.')

    return {
        'lines': len(parsed),
        'units': sum(i['qty'] for i in parsed),
        'total': total,
        'created': sum(1 for i in parsed if i.get('created')),
    }
