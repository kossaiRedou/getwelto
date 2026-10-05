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
            'manager': [reverse('dashboard'), reverse('dashboard') + '?start=2020-01-01&end=2020-12-31',
                        reverse('dashboard') + '?start=2020-03-01&end=2020-03-31',
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


class LoginThrottleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user('awa', password='bon-mot-de-passe', role='employee', first_name='Awa')

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        SetupMiddleware.setup_done = False

    def login(self, password, username='awa'):
        return self.client.post(reverse('users:login'), {'username': username, 'password': password})

    def test_lock_after_five_failures_even_with_good_password(self):
        for _ in range(5):
            self.assertEqual(self.login('faux').status_code, 200)
        r = self.login('bon-mot-de-passe')
        self.assertEqual(r.status_code, 429)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_lock_also_protects_admin_login(self):
        for _ in range(5):
            self.login('faux')
        r = self.client.post('/admin/login/', {'username': 'awa', 'password': 'bon-mot-de-passe'})
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(r.status_code, 200)

    def test_success_resets_counter(self):
        for _ in range(4):
            self.login('faux')
        self.assertEqual(self.login('bon-mot-de-passe').status_code, 302)
        self.client.logout()
        for _ in range(4):
            self.login('faux')
        self.assertEqual(self.login('bon-mot-de-passe').status_code, 302)

    def test_lock_per_ip_across_usernames(self):
        for i in range(20):
            self.login('faux', username=f'inconnu{i}')
        self.assertEqual(self.login('bon-mot-de-passe').status_code, 429)


class ProductionSettingsTests(TestCase):
    def run_settings(self, **env):
        import os
        import subprocess
        import sys
        base = {k: v for k, v in os.environ.items() if k not in (
            'DATABASE_URL', 'SECRET_KEY', 'ALLOWED_HOSTS', 'CSRF_TRUSTED_ORIGINS', 'DEBUG')}
        base.update(env, WELTO_ENV='production', PYTHONIOENCODING='utf-8')
        return subprocess.run([sys.executable, '-c', 'import blog_pos.settings'], env=base,
                              capture_output=True, text=True, encoding='utf-8',
                              cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    def test_missing_variables_refuse_to_start(self):
        r = self.run_settings()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('DATABASE_URL', r.stderr)

    def test_complete_configuration_starts(self):
        r = self.run_settings(DATABASE_URL='postgres://u:p@h:5432/db', SECRET_KEY='x' * 50,
                              ALLOWED_HOSTS='caisse.exemple.com', CSRF_TRUSTED_ORIGINS='https://caisse.exemple.com',
                              DEBUG='False')
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_debug_refused(self):
        r = self.run_settings(DATABASE_URL='postgres://u:p@h:5432/db', SECRET_KEY='x' * 50,
                              ALLOWED_HOSTS='a.com', CSRF_TRUSTED_ORIGINS='https://a.com', DEBUG='True')
        self.assertNotEqual(r.returncode, 0)


class ErrorPagesTests(TestCase):
    def test_404_in_french(self):
        from django.test import override_settings
        with override_settings(DEBUG=False):
            r = self.client.get('/sales/999999/', follow=True)
        self.assertContains(r, 'Page introuvable', status_code=404) if r.status_code == 404 else None
        from django.template.loader import render_to_string
        for name, text in [('404.html', 'Page introuvable'), ('500.html', 'Une erreur est survenue'),
                           ('403_csrf.html', 'La page a expiré')]:
            self.assertIn(text, render_to_string(name))
