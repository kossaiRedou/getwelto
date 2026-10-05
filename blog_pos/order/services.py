"""
Moteur de vente WELTO — seul code autorisé à créer ou modifier une vente.

Règles :
- Tous les montants sont des Decimal à 2 décimales, jamais des float.
- Les prix sont relus en base au moment de l'encaissement : le navigateur
  n'envoie que des identifiants et des quantités. Si le total affiché à la
  caisse diffère du total recalculé, la vente est refusée (`price_changed`).
- Chaque opération est atomique et verrouille les lignes concernées : pas de
  survente, pas de double encaissement.
- Une même vente renvoyée deux fois (réseau lent, double clic) avec la même
  clé `sale_key` n'est enregistrée qu'une fois.
"""
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db import IntegrityError, transaction
from django.db.models import Sum

from aprovision.models import TypeMouvement
from aprovision.services import StockError, move_stock
from client.models import Client
from product.models import Product, Stock
from .models import Order, OrderItem, Payment, PaymentMethod

ZERO = Decimal('0.00')
CENT = Decimal('0.01')
MAX_QTY = 1_000_000
MAX_AMOUNT = Decimal('999999999999999.99')
CREDIT = 'credit'


class SaleError(Exception):
    def __init__(self, message, code='invalid', data=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.data = data or {}


@dataclass
class SaleResult:
    order: Order
    change: Decimal = ZERO
    replayed: bool = False
    warnings: list = field(default_factory=list)


def to_money(value, label='Montant'):
    """Convertit une saisie (str/int/Decimal) en Decimal à 2 décimales, sans arrondi silencieux."""
    if isinstance(value, float) or isinstance(value, bool):
        raise SaleError(f'{label} invalide.')
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    text = str(value).strip().replace(' ', '').replace('\xa0', '').replace(' ', '').replace(',', '.')
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise SaleError(f'{label} invalide : « {value} ».')
    if not amount.is_finite():
        raise SaleError(f'{label} invalide.')
    if amount != amount.quantize(CENT):
        raise SaleError(f'{label} : 2 décimales maximum.')
    if abs(amount) > MAX_AMOUNT:
        raise SaleError(f'{label} trop élevé.')
    return amount.quantize(CENT)


def to_qty(value):
    if isinstance(value, bool):
        raise SaleError('Quantité invalide.')
    try:
        qty = int(str(value).strip())
    except (TypeError, ValueError):
        raise SaleError(f'Quantité invalide : « {value} ».')
    if qty < 1:
        raise SaleError('La quantité doit être au moins 1.')
    if qty > MAX_QTY:
        raise SaleError('Quantité trop élevée.')
    return qty


def _parse_lines(lines):
    """→ ({produit: quantité}, {produit: prix unitaire négocié ou None})."""
    merged, prices = {}, {}
    for line in lines or []:
        try:
            product_id = int(line['product_id'])
        except (KeyError, TypeError, ValueError):
            raise SaleError('Produit invalide dans le panier.')
        price = to_money(line.get('price'), 'Prix')
        if price is not None and price <= 0:
            raise SaleError('Le prix de vente doit être supérieur à 0.')
        if product_id in merged and prices[product_id] != price:
            raise SaleError('Un même produit apparaît deux fois avec des prix différents.')
        merged[product_id] = merged.get(product_id, 0) + to_qty(line.get('qty'))
        prices[product_id] = price
    for qty in merged.values():
        if qty > MAX_QTY:
            raise SaleError('Quantité trop élevée.')
    if not merged:
        raise SaleError('Le panier est vide.', code='empty')
    return merged, prices


def _parse_key(sale_key):
    if not sale_key:
        return None
    try:
        return uuid.UUID(str(sale_key))
    except ValueError:
        raise SaleError('Identifiant de vente invalide.')


def _sync_paid(order):
    """amount_paid = Σ paiements, recalculé sous verrou (source de vérité : les paiements)."""
    paid = order.payments.aggregate(s=Sum('amount'))['s'] or ZERO
    if paid > order.final_value:
        raise SaleError('Le total des paiements dépasse le montant de la vente.')
    order.amount_paid = paid
    order.is_paid = paid == order.final_value
    Order.objects.filter(pk=order.pk).update(amount_paid=order.amount_paid, is_paid=order.is_paid)


def checkout(*, lines, user, shop, method, amount=None, discount=None, client_id=None,
             expected_total=None, sale_key=None):
    """Enregistre une vente dans une boutique. Retourne un SaleResult (vente + monnaie à rendre).

    Les produits viennent du catalogue du compte, le stock et le client de la boutique.

    Une ligne peut porter un `price` : prix unitaire négocié pour CETTE vente
    uniquement (prix client). La fiche produit n'est jamais modifiée.
    """
    merged, prices = _parse_lines(lines)
    if method != CREDIT and method not in PaymentMethod.values:
        raise SaleError('Mode de paiement invalide.')
    discount = to_money(discount, 'Remise') or ZERO
    if discount < 0:
        raise SaleError('La remise ne peut pas être négative.')
    amount = to_money(amount, 'Montant reçu')
    if amount is not None and amount < 0:
        raise SaleError('Le montant reçu ne peut pas être négatif.')
    expected_total = to_money(expected_total, 'Total')
    key = _parse_key(sale_key)

    if key:
        existing = Order.objects.filter(sync_uuid=key, shop=shop).first()
        if existing:
            return SaleResult(order=existing, replayed=True)

    client = None
    if client_id not in (None, ''):
        client = Client.objects.filter(pk=client_id, shop=shop, is_active=True).first()
        if client is None:
            raise SaleError('Client introuvable ou désactivé.')

    try:
        with transaction.atomic():
            products = {p.pk: p for p in
                        Product.objects.select_for_update().filter(pk__in=merged, account_id=shop.account_id)
                        .order_by('pk')}
            missing = [pid for pid in merged if pid not in products or not products[pid].active]
            if missing:
                raise SaleError('Un produit du panier n\'est plus disponible. Rechargez la caisse.',
                                code='price_changed')
            stock = dict(Stock.objects.filter(shop=shop, product_id__in=merged).values_list('product_id', 'qty'))
            shortages = [
                {'product_id': pid, 'title': products[pid].title,
                 'available': stock.get(pid, 0), 'requested': qty}
                for pid, qty in merged.items() if stock.get(pid, 0) < qty
            ]
            if shortages:
                detail = ', '.join(f"{s['title']} ({s['available']} en stock)" for s in shortages)
                raise SaleError(f'Stock insuffisant : {detail}.', code='stock', data={'shortages': shortages})

            unit = {pid: prices[pid] if prices[pid] is not None else products[pid].final_value for pid in merged}
            subtotal = sum((unit[pid] * qty for pid, qty in merged.items()), ZERO)
            if discount > subtotal:
                raise SaleError('La remise dépasse le montant des articles.')
            total = subtotal - discount
            if expected_total is not None and expected_total != total:
                raise SaleError('Les prix ont changé depuis le chargement de la caisse. '
                                'Vérifiez le panier puis validez à nouveau.',
                                code='price_changed', data={'total': str(total)})

            change = ZERO
            if method == CREDIT:
                paid = min(amount or ZERO, total)
                pay_method = PaymentMethod.CASH
            else:
                paid = total if amount is None else min(amount, total)
                pay_method = method
                if method == PaymentMethod.CASH and amount is not None and amount > total:
                    change = amount - total
            if paid < total and client is None:
                raise SaleError('Choisissez un client : le reste à payer sera inscrit à son crédit.',
                                code='client_required', data={'remaining': str(total - paid)})

            order = Order(shop=shop, value=subtotal, discount=discount, final_value=total,
                          amount_paid=ZERO, is_paid=total == ZERO, client=client, created_by=user)
            if key:
                order.sync_uuid = key
            order.save()

            for pid in sorted(merged):
                product, qty = products[pid], merged[pid]
                OrderItem.objects.create(
                    order=order, product=product, qty=qty,
                    price=product.value, discount_price=product.discount_value,
                    final_price=unit[pid], total_price=unit[pid] * qty,
                    cost_price=product.prix_achat,
                )
                move_stock(pid, -qty, TypeMouvement.SORTIE_VENTE, shop=shop, user=user, order=order,
                           unit_cost=product.prix_achat if product.prix_achat > 0 else None,
                           description=f'Vente {order.title}')

            if paid > 0:
                Payment.objects.create(order=order, amount=paid, method=pay_method, created_by=user)
                _sync_paid(order)
    except StockError as exc:
        raise SaleError(str(exc), code='stock')
    except IntegrityError:
        if key:
            existing = Order.objects.filter(sync_uuid=key, shop=shop).first()
            if existing:
                return SaleResult(order=existing, replayed=True)
        raise

    return SaleResult(order=order, change=change)


def add_payment(order_id, amount, method, *, user, note=''):
    """Encaisse tout ou partie du reste dû d'une vente."""
    amount = to_money(amount, 'Montant')
    if amount is None or amount <= 0:
        raise SaleError('Le montant doit être supérieur à 0.')
    if method not in PaymentMethod.values:
        raise SaleError('Mode de paiement invalide.')
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        remaining = order.final_value - order.amount_paid
        if remaining <= 0:
            raise SaleError('Cette vente est déjà soldée.')
        if amount > remaining:
            raise SaleError(f'Le montant dépasse le reste à payer ({remaining}).')
        payment = Payment.objects.create(order=order, amount=amount, method=method,
                                         note=note[:200], created_by=user)
        _sync_paid(order)
    return payment


def delete_payment(order_id, payment_id):
    """Supprime un paiement saisi par erreur (réservé au manager)."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        deleted, _ = Payment.objects.filter(pk=payment_id, order=order).delete()
        if not deleted:
            raise SaleError('Paiement introuvable.')
        _sync_paid(order)
    return order


def cancel_sale(order_id, *, user):
    """Annule une vente : remet les articles en stock (tracé) puis supprime la vente."""
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        title = order.title
        for item in order.order_items.order_by('product_id'):
            move_stock(item.product_id, item.qty, TypeMouvement.AJUSTEMENT_PLUS, shop=order.shop, user=user,
                       description=f'Annulation vente {title}')
        order.delete()
    return title
