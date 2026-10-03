from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from aprovision.services import adjust_stock, restock
from client.models import Client
from core.utils import format_money
from order.services import checkout
from product.models import Category, Product
from users.middleware import SetupMiddleware
from users.models import AppSetting, User


class FormatTests(TestCase):
    def test_format_money(self):
        self.assertEqual(format_money(Decimal('38000')), '38 000')
        self.assertEqual(format_money(Decimal('1250.5')), '1 250,50')
        self.assertEqual(format_money(Decimal('-15')), '-15')
        self.assertEqual(format_money(None), '0')


class SetupFlowTests(TestCase):
    def setUp(self):
        SetupMiddleware.setup_done = False

    def test_first_launch_redirects_to_setup_and_creates_shop(self):
        self.assertRedirects(self.client.get('/'), reverse('users:setup'))
        r = self.client.post(reverse('users:setup'), {
            'company_name': 'Boutique Kaloum', 'currency_label': 'GNF', 'first_name': 'Aliou', 'last_name': 'Diallo',
            'username': 'aliou', 'email': 'a@example.com', 'phone': '622000000',
            'password1': 'unmotdepasse-solide', 'password2': 'unmotdepasse-solide',
        })
        self.assertRedirects(r, reverse('product:add_product'))
        user = User.objects.get()
        self.assertEqual(user.role, 'manager')
        self.assertEqual(AppSetting.get_solo().company_name, 'Boutique Kaloum')
        self.assertEqual(AppSetting.get_solo().currency_label, 'GNF')
        self.assertEqual(self.client.get('/').status_code, 200)


class PagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('chef', password='x' * 10, role='manager', first_name='Chef')
        cls.employee = User.objects.create_user('caisse', password='x' * 10, role='employee', first_name='Awa')
        cls.other = User.objects.create_user('autre', password='x' * 10, role='employee', first_name='Bob')
        cat = Category.objects.create(title='Boissons')
        cls.product = Product.objects.create(title='Coca', value=Decimal('2000'), category=cat, barcode='5449000000996')
        restock(cls.product.pk, 20, '1500', user=cls.manager)
        adjust_stock(cls.product.pk, 'remove', 1, user=cls.manager)
        cls.customer = Client.objects.create(name='Mariama', phone='622111222')
        cls.order = checkout(lines=[{'product_id': cls.product.pk, 'qty': 3}], user=cls.employee, method='credit',
                             amount='1000', client_id=cls.customer.pk).order

    def setUp(self):
        SetupMiddleware.setup_done = False

    def pages(self):
        o, p, c = self.order.pk, self.product.pk, self.customer.pk
        return {
            'all': [reverse('pos'), reverse('order_list'), reverse('order_list') + '?status=unpaid&q=V&start=2020-01-01',
                    reverse('order_detail', args=[o]), reverse('order_ticket', args=[o]),
                    reverse('product:product_list'), reverse('product:product_list') + '?status=low',
                    reverse('client:client_list'), reverse('client:client_list') + '?status=debt',
                    reverse('client:client_detail', args=[c]), reverse('client:add_client'),
                    reverse('client:edit_client', args=[c]), reverse('users:my_password_change')],
            'manager': [reverse('dashboard'), reverse('aprovision:reports'),
                        reverse('aprovision:reports') + '?start=2020-01-01&end=2020-12-31',
                        reverse('aprovision:depense_list'), reverse('aprovision:nouvelle_depense'),
                        reverse('aprovision:mouvement_list'), reverse('product:add_product'),
                        reverse('product:edit_product', args=[p]), reverse('product:quick_stock', args=[p]),
                        reverse('product:category_management'), reverse('product:delete_product', args=[p]),
                        reverse('users:user_list'), reverse('users:user_create'),
                        reverse('users:user_update', args=[self.other.pk]),
                        reverse('users:change_password', args=[self.other.pk]),
                        reverse('users:app_settings')],
        }

    def test_manager_sees_everything(self):
        self.client.force_login(self.manager)
        for url in self.pages()['all'] + self.pages()['manager']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_employee_is_kept_out_of_management(self):
        self.client.force_login(self.employee)
        for url in self.pages()['all']:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        for url in self.pages()['manager']:
            with self.subTest(url=url):
                self.assertRedirects(self.client.get(url), reverse('pos'), fetch_redirect_response=False)

    def test_anonymous_redirected_to_login(self):
        r = self.client.get(reverse('order_list'))
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('users:login'), r['Location'])

    def test_invoice_pdf(self):
        self.client.force_login(self.employee)
        r = self.client.get(reverse('invoice_pdf', args=[self.order.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r['Content-Type'], 'application/pdf')

    def test_pay_debt_from_detail_page(self):
        self.client.force_login(self.employee)
        r = self.client.post(reverse('order_add_payment', args=[self.order.pk]), {'amount': '5000', 'method': 'mobile'})
        self.assertRedirects(r, self.order.get_absolute_url())
        self.order.refresh_from_db()
        self.assertTrue(self.order.is_paid)

    def test_employee_cannot_cancel(self):
        self.client.force_login(self.employee)
        self.client.post(reverse('order_cancel', args=[self.order.pk]))
        self.assertTrue(type(self.order).objects.filter(pk=self.order.pk).exists())

    def test_manager_cancel(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('order_cancel', args=[self.order.pk]))
        self.assertRedirects(r, reverse('order_list'))
        self.product.refresh_from_db()
        self.assertEqual(self.product.qty, 19)

    def test_product_form_with_initial_stock(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('product:add_product'), {
            'title': 'Riz 5kg', 'value': '25000', 'discount_value': '0', 'prix_achat': '21000',
            'initial_qty': '12', 'active': 'on', 'barcode': ''})
        self.assertRedirects(r, reverse('product:product_list'))
        riz = Product.objects.get(title='Riz 5kg')
        self.assertEqual((riz.qty, riz.barcode), (12, None))

    def test_stock_restock_form(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('product:quick_stock', args=[self.product.pk]),
                             {'action': 'restock', 'quantity': '10', 'unit_cost': '1600'})
        self.assertRedirects(r, reverse('product:product_list'))
        self.product.refresh_from_db()
        self.assertEqual((self.product.qty, self.product.prix_achat), (26, Decimal('1600')))

    def test_sold_product_cannot_be_deleted(self):
        self.client.force_login(self.manager)
        self.client.post(reverse('product:delete_product', args=[self.product.pk]))
        self.assertTrue(Product.objects.filter(pk=self.product.pk).exists())

    def test_expense_form(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('aprovision:nouvelle_depense'), {
            'new_type': 'Loyer', 'montant': '500000', 'date_depense': '2026-10-01', 'description': 'Loyer octobre'})
        self.assertRedirects(r, reverse('aprovision:depense_list'))

    def test_logout_requires_post(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse('users:logout')).status_code, 405)
        self.assertRedirects(self.client.post(reverse('users:logout')), reverse('users:login'))
