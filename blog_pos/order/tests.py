import json
import uuid
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from aprovision.models import Depense, MouvementStock, TypeMouvement
from aprovision.services import StockError, adjust_stock, restock
from client.models import Client
from product.models import Product
from users.middleware import SetupMiddleware
from users.models import User
from . import services
from .models import Order, Payment
from .services import SaleError, checkout

D = Decimal


class SaleTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('caisse', password='motdepasse123', role='employee', first_name='Awa')
        cls.manager = User.objects.create_user('chef', password='motdepasse123', role='manager', first_name='Chef')

    def setUp(self):
        SetupMiddleware.setup_done = False
        self.coca = self.make_product('Coca-Cola 1L', '2000', qty=50, cost='1500')
        self.riz = self.make_product('Riz 5kg', '25000', qty=10, cost='21000')
        self.savon = self.make_product('Savon', '3000', qty=30, cost='2000')
        self.client_ = Client.objects.create(name='Mamadou Bah', phone='622123456')

    def make_product(self, title, price, qty=0, cost='0', promo='0'):
        p = Product.objects.create(title=title, value=D(price), discount_value=D(promo), prix_achat=D(cost))
        if qty:
            adjust_stock(p.pk, 'add', qty, description='init')
        p.refresh_from_db()
        return p

    def sell(self, lines, method='cash', **kwargs):
        return checkout(lines=[{'product_id': p.pk, 'qty': q} for p, q in lines],
                        user=self.user, method=method, **kwargs)

    def qty(self, product):
        product.refresh_from_db()
        return product.qty


class CheckoutTests(SaleTestCase):
    def test_image_example_cash_sale(self):
        """L'exemple de la maquette : 2 Coca + 1 riz + 3 savons = 38 000."""
        result = self.sell([(self.coca, 2), (self.riz, 1), (self.savon, 3)], amount='40000')
        order = result.order
        self.assertEqual(order.value, D('38000.00'))
        self.assertEqual(order.final_value, D('38000.00'))
        self.assertEqual(order.amount_paid, D('38000.00'))
        self.assertTrue(order.is_paid)
        self.assertEqual(result.change, D('2000.00'))
        self.assertEqual(order.payments.get().amount, D('38000.00'))
        self.assertEqual(order.created_by, self.user)
        self.assertEqual(order.title, f'V-{order.pk:06d}')
        self.assertEqual(self.qty(self.coca), 48)
        self.assertEqual(self.qty(self.riz), 9)
        self.assertEqual(self.qty(self.savon), 27)

    def test_stock_movements_are_exact(self):
        order = self.sell([(self.coca, 5)]).order
        mv = MouvementStock.objects.get(reference_commande=order)
        self.assertEqual(mv.type_mouvement, TypeMouvement.SORTIE_VENTE)
        self.assertEqual((mv.quantite, mv.stock_avant, mv.stock_apres), (-5, 50, 45))
        self.assertEqual(mv.cout_total, D('7500.00'))

    def test_exact_amount_default_when_no_amount(self):
        result = self.sell([(self.savon, 1)], method='mobile')
        self.assertEqual(result.order.amount_paid, D('3000.00'))
        self.assertEqual(result.change, D('0'))
        self.assertEqual(result.order.payments.get().method, 'mobile')

    def test_overpay_by_card_is_capped_without_change(self):
        result = self.sell([(self.savon, 1)], method='card', amount='5000')
        self.assertEqual(result.order.amount_paid, D('3000.00'))
        self.assertEqual(result.change, D('0'))

    def test_decimal_precision(self):
        p = self.make_product('Bonbon', '33.33', qty=10)
        order = self.sell([(p, 3)]).order
        self.assertEqual(order.final_value, D('99.99'))
        self.assertEqual(order.order_items.get().total_price, D('99.99'))

    def test_promo_price_is_used(self):
        p = self.make_product('Huile', '10000', qty=5, promo='8500')
        order = self.sell([(p, 2)]).order
        item = order.order_items.get()
        self.assertEqual((item.price, item.discount_price, item.final_price), (D('10000'), D('8500'), D('8500')))
        self.assertEqual(order.final_value, D('17000.00'))

    def test_duplicate_lines_are_merged(self):
        order = self.sell([(self.coca, 1), (self.coca, 2)]).order
        self.assertEqual(order.order_items.get().qty, 3)
        self.assertEqual(self.qty(self.coca), 47)

    def test_discount(self):
        order = self.sell([(self.riz, 2)], discount='5000').order
        self.assertEqual((order.value, order.discount, order.final_value), (D('50000'), D('5000'), D('45000')))
        self.assertEqual(order.amount_paid, D('45000'))

    def test_discount_greater_than_total_is_refused(self):
        with self.assertRaises(SaleError):
            self.sell([(self.savon, 1)], discount='3000.01')
        self.assertFalse(Order.objects.exists())

    def test_full_discount_sale_is_paid(self):
        order = self.sell([(self.savon, 1)], discount='3000').order
        self.assertEqual(order.final_value, D('0'))
        self.assertTrue(order.is_paid)
        self.assertFalse(order.payments.exists())

    def test_insufficient_stock_rolls_back_everything(self):
        with self.assertRaises(SaleError) as ctx:
            self.sell([(self.coca, 2), (self.riz, 11)])
        self.assertEqual(ctx.exception.code, 'stock')
        self.assertEqual(ctx.exception.data['shortages'][0]['available'], 10)
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.qty(self.coca), 50)
        self.assertEqual(self.qty(self.riz), 10)

    def test_inactive_product_is_refused(self):
        Product.objects.filter(pk=self.coca.pk).update(active=False)
        with self.assertRaises(SaleError):
            self.sell([(self.coca, 1)])

    def test_price_changed_since_cart_was_built(self):
        Product.objects.filter(pk=self.coca.pk).update(value=D('2500'), final_value=D('2500'))
        with self.assertRaises(SaleError) as ctx:
            self.sell([(self.coca, 2)], expected_total='4000')
        self.assertEqual(ctx.exception.code, 'price_changed')
        self.assertEqual(ctx.exception.data['total'], '5000.00')
        self.assertEqual(self.qty(self.coca), 50)

    def test_expected_total_ok(self):
        self.sell([(self.coca, 2)], expected_total='4000.00')
        self.assertEqual(Order.objects.count(), 1)

    def test_partial_payment_requires_client(self):
        with self.assertRaises(SaleError) as ctx:
            self.sell([(self.riz, 1)], amount='10000')
        self.assertEqual(ctx.exception.code, 'client_required')
        self.assertEqual(ctx.exception.data['remaining'], '15000.00')
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.qty(self.riz), 10)

    def test_partial_payment_with_client(self):
        order = self.sell([(self.riz, 1)], amount='10000', client_id=self.client_.pk).order
        self.assertFalse(order.is_paid)
        self.assertEqual(order.amount_paid, D('10000'))
        self.assertEqual(order.remaining_amount(), D('15000'))
        self.assertEqual(self.client_.total_unpaid_amount(), D('15000'))

    def test_credit_sale(self):
        order = self.sell([(self.riz, 2)], method='credit', client_id=self.client_.pk).order
        self.assertFalse(order.is_paid)
        self.assertEqual(order.amount_paid, D('0'))
        self.assertFalse(order.payments.exists())
        self.assertEqual(self.client_.total_unpaid_amount(), D('50000'))

    def test_credit_with_deposit_is_cash(self):
        order = self.sell([(self.riz, 2)], method='credit', amount='20000', client_id=self.client_.pk).order
        self.assertEqual(order.payments.get().method, 'cash')
        self.assertEqual(order.remaining_amount(), D('30000'))

    def test_credit_requires_client(self):
        with self.assertRaises(SaleError) as ctx:
            self.sell([(self.riz, 1)], method='credit')
        self.assertEqual(ctx.exception.code, 'client_required')

    def test_inactive_client_refused(self):
        Client.objects.filter(pk=self.client_.pk).update(is_active=False)
        with self.assertRaises(SaleError):
            self.sell([(self.riz, 1)], method='credit', client_id=self.client_.pk)

    def test_idempotent_retry(self):
        key = str(uuid.uuid4())
        first = self.sell([(self.coca, 3)], sale_key=key)
        second = self.sell([(self.coca, 3)], sale_key=key)
        self.assertEqual(first.order.pk, second.order.pk)
        self.assertTrue(second.replayed)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.qty(self.coca), 47)

    def test_invalid_inputs(self):
        bad = [
            dict(lines=[]),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 0}]),
            dict(lines=[{'product_id': self.coca.pk, 'qty': -1}]),
            dict(lines=[{'product_id': self.coca.pk, 'qty': '1.5'}]),
            dict(lines=[{'product_id': self.coca.pk, 'qty': True}]),
            dict(lines=[{'product_id': 'abc', 'qty': 1}]),
            dict(lines=[{'product_id': 999999, 'qty': 1}]),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 1}], amount=2000.0),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 1}], amount='12.345'),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 1}], amount='-5'),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 1}], discount='-1'),
            dict(lines=[{'product_id': self.coca.pk, 'qty': 1}], sale_key='pas-un-uuid'),
        ]
        for kwargs in bad:
            kwargs.setdefault('method', 'cash')
            with self.subTest(kwargs=kwargs), self.assertRaises(SaleError):
                checkout(user=self.user, **kwargs)
        with self.assertRaises(SaleError):
            self.sell([(self.coca, 1)], method='bitcoin')
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.qty(self.coca), 50)

    def test_amount_formats(self):
        self.assertEqual(services.to_money('40 000'), D('40000.00'))
        self.assertEqual(services.to_money('1250,5'), D('1250.50'))
        self.assertEqual(services.to_money(40000), D('40000.00'))
        self.assertIsNone(services.to_money(''))


class PaymentAndCancelTests(SaleTestCase):
    def credit_order(self):
        return self.sell([(self.riz, 2)], method='credit', client_id=self.client_.pk).order

    def test_pay_debt_in_two_steps(self):
        order = self.credit_order()
        services.add_payment(order.pk, '20000', 'cash', user=self.user)
        order.refresh_from_db()
        self.assertEqual((order.amount_paid, order.is_paid), (D('20000'), False))
        services.add_payment(order.pk, '30000', 'mobile', user=self.user)
        order.refresh_from_db()
        self.assertEqual((order.amount_paid, order.is_paid), (D('50000'), True))
        self.assertEqual(self.client_.total_unpaid_amount(), D('0'))

    def test_overpayment_refused(self):
        order = self.credit_order()
        with self.assertRaises(SaleError):
            services.add_payment(order.pk, '50000.01', 'cash', user=self.user)
        services.add_payment(order.pk, '50000', 'cash', user=self.user)
        with self.assertRaises(SaleError):
            services.add_payment(order.pk, '1', 'cash', user=self.user)

    def test_invalid_payment(self):
        order = self.credit_order()
        for amount, method in [('0', 'cash'), ('-10', 'cash'), ('abc', 'cash'), ('10', 'credit')]:
            with self.subTest(amount=amount, method=method), self.assertRaises(SaleError):
                services.add_payment(order.pk, amount, method, user=self.user)

    def test_delete_payment_recomputes(self):
        order = self.credit_order()
        payment = services.add_payment(order.pk, '50000', 'cash', user=self.user)
        services.delete_payment(order.pk, payment.pk)
        order.refresh_from_db()
        self.assertEqual((order.amount_paid, order.is_paid), (D('0'), False))

    def test_cancel_sale_restores_stock_with_trace(self):
        order = self.sell([(self.coca, 4), (self.savon, 2)]).order
        title = services.cancel_sale(order.pk, user=self.manager)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.assertEqual(self.qty(self.coca), 50)
        self.assertEqual(self.qty(self.savon), 30)
        cancel_mv = MouvementStock.objects.get(produit=self.coca, description=f'Annulation vente {title}')
        self.assertEqual((cancel_mv.quantite, cancel_mv.stock_avant, cancel_mv.stock_apres), (4, 46, 50))
        self.assertTrue(MouvementStock.objects.filter(description=f'Vente {title}').exists())


class StockServiceTests(SaleTestCase):
    def test_restock_creates_expense_and_entry(self):
        mv = restock(self.riz.pk, 20, '20500', user=self.manager, fournisseur='Grossiste')
        self.assertEqual(self.qty(self.riz), 30)
        self.assertEqual((mv.stock_avant, mv.stock_apres, mv.cout_total), (10, 30, D('410000')))
        depense = Depense.objects.get()
        self.assertEqual(depense.montant, D('410000'))
        self.assertEqual(depense.type_depense.nom, 'Approvisionnement')
        self.riz.refresh_from_db()
        self.assertEqual(self.riz.prix_achat, D('20500'))

    def test_adjust_set_and_remove(self):
        adjust_stock(self.savon.pk, 'set', 12, user=self.manager)
        self.assertEqual(self.qty(self.savon), 12)
        mv = adjust_stock(self.savon.pk, 'remove', 2, user=self.manager)
        self.assertEqual((mv.type_mouvement, mv.stock_avant, mv.stock_apres), (TypeMouvement.SORTIE_PERTE, 12, 10))
        self.assertIsNone(adjust_stock(self.savon.pk, 'set', 10, user=self.manager))

    def test_cannot_go_negative(self):
        with self.assertRaises(StockError):
            adjust_stock(self.riz.pk, 'remove', 11, user=self.manager)
        self.assertEqual(self.qty(self.riz), 10)

    def test_sale_cost_snapshot(self):
        order = self.sell([(self.riz, 1)]).order
        Product.objects.filter(pk=self.riz.pk).update(prix_achat=D('99999'))
        self.assertEqual(order.order_items.get().cost_price, D('21000'))


class DatabaseConstraintTests(SaleTestCase):
    def test_inconsistent_order_rejected_by_database(self):
        order = self.sell([(self.coca, 1)]).order
        for values in [dict(is_paid=False), dict(amount_paid=D('3000')), dict(final_value=D('1')),
                       dict(discount=D('5000'))]:
            with self.subTest(values=values), self.assertRaises(IntegrityError), transaction.atomic():
                Order.objects.filter(pk=order.pk).update(**values)

    def test_negative_stock_rejected_by_database(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=self.coca.pk).update(qty=-1)


class ApiTests(SaleTestCase):
    def post_json(self, url, data):
        return self.client.post(url, json.dumps(data), content_type='application/json')

    def test_api_requires_login(self):
        self.assertEqual(self.client.get(reverse('api_catalog')).status_code, 401)
        self.assertEqual(self.post_json(reverse('api_checkout'), {}).status_code, 401)

    def test_catalog_and_etag(self):
        self.client.force_login(self.user)
        r = self.client.get(reverse('api_catalog'))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        row = next(p for p in data['products'] if p[0] == self.coca.pk)
        self.assertEqual(row[3], 200000)  # prix en centimes
        self.assertEqual(row[4], 50)
        etag = r['ETag']
        self.assertEqual(self.client.get(reverse('api_catalog'), HTTP_IF_NONE_MATCH=etag).status_code, 304)
        self.sell([(self.coca, 1)])
        r2 = self.client.get(reverse('api_catalog'), HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(next(p for p in r2.json()['products'] if p[0] == self.coca.pk)[4], 49)

    def test_checkout_endpoint(self):
        self.client.force_login(self.user)
        r = self.post_json(reverse('api_checkout'), {
            'lines': [{'product_id': self.coca.pk, 'qty': 2}],
            'method': 'cash', 'amount': '5000', 'expected_total': '4000.00', 'sale_key': str(uuid.uuid4()),
        })
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['order']['total'], 400000)
        self.assertEqual(body['order']['change'], 100000)

    def test_checkout_endpoint_errors(self):
        self.client.force_login(self.user)
        r = self.post_json(reverse('api_checkout'), {'lines': [{'product_id': self.riz.pk, 'qty': 99}],
                                                     'method': 'cash'})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(r.json()['code'], 'stock')
        r = self.client.post(reverse('api_checkout'), 'pas du json', content_type='application/json')
        self.assertEqual(r.status_code, 400)

    def test_client_api(self):
        self.client.force_login(self.user)
        r = self.post_json(reverse('client:api_create'), {'name': 'Fatou', 'phone': '+220 712 3456'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['client']['phone'], '+2207123456')
        r = self.post_json(reverse('client:api_create'), {'name': 'Fatou 2', 'phone': '+2207123456'})
        self.assertEqual(r.status_code, 400)
        self.sell([(self.riz, 1)], method='credit', client_id=self.client_.pk)
        found = self.client.get(reverse('client:api_search'), {'q': 'mamadou'}).json()['clients']
        self.assertEqual(found[0]['debt'], 2500000)
