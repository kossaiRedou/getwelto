import json
import uuid
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from product.models import Category, Product
from users.middleware import SetupMiddleware
from users.models import User
from .models import Depense, MouvementStock, TypeMouvement
from .services import StockError, adjust_stock, receive

D = Decimal


class ReceptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('chef', password='x' * 10, role='manager')
        cls.employee = User.objects.create_user('caisse', password='x' * 10, role='employee')
        cls.cat = Category.objects.create(title='Épicerie')

    def setUp(self):
        SetupMiddleware.setup_done = False
        self.riz = Product.objects.create(title='Riz 5kg', value=D('25000'), prix_achat=D('20000'))
        adjust_stock(self.riz.pk, 'add', 10, description='init')
        self.huile = Product.objects.create(title='Huile 1L', value=D('12000'), barcode='111')

    def qty(self, product):
        product.refresh_from_db()
        return product.qty

    def test_existing_and_new_products_in_one_reception(self):
        result = receive([
            {'product_id': self.riz.pk, 'qty': 20, 'unit_cost': '21000', 'price': '26000'},
            {'product_id': self.huile.pk, 'qty': 6, 'unit_cost': '10000.50'},
            {'new': {'title': 'Sucre 1kg', 'barcode': '6001234567890', 'category_id': self.cat.pk, 'price': '8000'},
             'qty': 12, 'unit_cost': '6500'},
        ], user=self.manager, fournisseur='Grossiste Madina', reference='F-42')
        self.assertEqual((result['lines'], result['units'], result['created']), (3, 38, 1))
        self.assertEqual(result['total'], D('420000') + D('60003.00') + D('78000'))

        self.riz.refresh_from_db()
        self.assertEqual((self.riz.qty, self.riz.prix_achat, self.riz.value, self.riz.final_value),
                         (30, D('21000'), D('26000'), D('26000')))
        self.huile.refresh_from_db()
        self.assertEqual((self.huile.qty, self.huile.prix_achat, self.huile.value), (6, D('10000.50'), D('12000')))
        sucre = Product.objects.get(title='Sucre 1kg')
        self.assertEqual((sucre.qty, sucre.barcode, sucre.category, sucre.value, sucre.prix_achat),
                         (12, '6001234567890', self.cat, D('8000'), D('6500')))

        depense = Depense.objects.get()
        self.assertEqual((depense.montant, depense.fournisseur, depense.reference), (result['total'], 'Grossiste Madina', 'F-42'))
        self.assertEqual(depense.type_depense.nom, 'Approvisionnement')
        entries = MouvementStock.objects.filter(type_mouvement=TypeMouvement.ENTREE)
        self.assertEqual(entries.count(), 3)
        self.assertTrue(all(m.reference_depense_id == depense.pk for m in entries))
        mv = entries.get(produit=self.riz)
        self.assertEqual((mv.stock_avant, mv.stock_apres, mv.cout_total), (10, 30, D('420000')))

    def test_idempotent(self):
        key = uuid.uuid4()
        lines = [{'product_id': self.riz.pk, 'qty': 5, 'unit_cost': '20000'}]
        self.assertIsNotNone(receive(lines, user=self.manager, key=key))
        self.assertIsNone(receive(lines, user=self.manager, key=key))
        self.assertEqual(self.qty(self.riz), 15)
        self.assertEqual(Depense.objects.count(), 1)

    def test_error_rolls_back_everything(self):
        with self.assertRaises(StockError):
            receive([
                {'product_id': self.riz.pk, 'qty': 5, 'unit_cost': '20000'},
                {'new': {'title': 'huile 1l', 'price': '9000'}, 'qty': 1, 'unit_cost': '7000'},
            ], user=self.manager)
        self.assertEqual(self.qty(self.riz), 10)
        self.assertFalse(Depense.objects.exists())
        self.assertEqual(Product.objects.count(), 2)

    def test_barcode_rules(self):
        with self.assertRaises(StockError):   # code déjà utilisé par un autre produit
            receive([{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '0', 'barcode': '111'}], user=self.manager)
        receive([{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '0', 'barcode': '222'}], user=self.manager)
        self.riz.refresh_from_db()
        self.assertEqual(self.riz.barcode, '222')
        with self.assertRaises(StockError):   # même code deux fois dans le bon
            receive([{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '0', 'barcode': '333'},
                     {'new': {'title': 'Sel', 'barcode': '333', 'price': '500'}, 'qty': 1, 'unit_cost': '0'}],
                    user=self.manager)

    def test_free_goods_create_no_expense(self):
        receive([{'product_id': self.huile.pk, 'qty': 3, 'unit_cost': '0'}], user=self.manager)
        self.assertEqual(self.qty(self.huile), 3)
        self.assertFalse(Depense.objects.exists())
        self.assertIsNone(MouvementStock.objects.get(produit=self.huile).cout_total)

    def test_price_below_promo_refused(self):
        Product.objects.filter(pk=self.riz.pk).update(discount_value=D('24000'), final_value=D('24000'))
        with self.assertRaises(StockError):
            receive([{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '20000', 'price': '23000'}], user=self.manager)

    def test_invalid_lines(self):
        bad = [
            [],
            [{'product_id': self.riz.pk, 'qty': 0, 'unit_cost': '1'}],
            [{'product_id': self.riz.pk, 'qty': 1}],
            [{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '-1'}],
            [{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '1.234'}],
            [{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': '1'}, {'product_id': self.riz.pk, 'qty': 2, 'unit_cost': '1'}],
            [{'product_id': 99999, 'qty': 1, 'unit_cost': '1'}],
            [{'new': {'title': 'X'}, 'qty': 1, 'unit_cost': '1'}],
            [{'new': {'title': 'Lait', 'price': '0'}, 'qty': 1, 'unit_cost': '1'}],
            [{'new': {'title': 'Lait', 'price': '900', 'category_id': 99999}, 'qty': 1, 'unit_cost': '1'}],
        ]
        for lines in bad:
            with self.subTest(lines=lines), self.assertRaises(StockError):
                receive(lines, user=self.manager)
        self.assertEqual(self.qty(self.riz), 10)

    def post(self, data):
        return self.client.post(reverse('product:api_receive'), json.dumps(data), content_type='application/json')

    def test_api_and_page_access(self):
        payload = {'lines': [{'product_id': self.riz.pk, 'qty': 2, 'unit_cost': '20000'}], 'key': str(uuid.uuid4())}
        self.assertEqual(self.post(payload).status_code, 401)
        self.client.force_login(self.employee)
        self.assertEqual(self.post(payload).status_code, 403)
        self.assertEqual(self.client.get(reverse('product:api_stock_catalog')).status_code, 403)
        self.assertRedirects(self.client.get(reverse('product:restock')), reverse('pos'), fetch_redirect_response=False)

        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('product:restock')).status_code, 200)
        r = self.post(payload)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()['units'], r.json()['total']), (2, 4000000))
        self.assertTrue(self.post(payload).json()['replayed'])
        self.assertEqual(self.qty(self.riz), 12)
        r = self.post({'lines': [{'product_id': self.riz.pk, 'qty': 1, 'unit_cost': 'abc'}]})
        self.assertEqual(r.status_code, 400)

    def test_stock_catalog_includes_inactive_and_cost(self):
        Product.objects.filter(pk=self.huile.pk).update(active=False)
        self.client.force_login(self.manager)
        rows = {r[1]: r for r in self.client.get(reverse('product:api_stock_catalog')).json()['products']}
        self.assertEqual(rows['Riz 5kg'][6], 2000000)   # prix d'achat en centimes
        self.assertEqual(rows['Huile 1L'][7], 0)        # retiré de la vente, mais présent
