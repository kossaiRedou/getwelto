import datetime
from decimal import Decimal

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from aprovision.models import Depense, TypeDepense
from aprovision.services import StockError, adjust_stock, receive
from client.models import Client
from core.testing import PASSWORD, make_account, make_employee, stock_qty
from order.models import Order
from order.services import SaleError, checkout
from product.models import Product
from users.models import AppSetting, User
from . import services
from .models import Account, Shop

D = Decimal


def login(client, user, password=PASSWORD):
    return client.post(reverse('users:login'), {'username': user.username, 'password': password})


class SignupTests(TestCase):
    data = {
        'company_name': 'Diallo & Fils', 'country': 'GM', 'shop_name': 'Serrekunda',
        'first_name': 'Aliou', 'last_name': 'Diallo', 'phone': '+220 700 00 00', 'email': 'aliou@example.com',
        'username': 'aliou', 'password1': 'un-mot-de-passe-solide', 'password2': 'un-mot-de-passe-solide',
    }

    def test_signup_creates_a_blocked_account(self):
        self.assertEqual(self.client.get(reverse('accounts:signup')).status_code, 200)
        r = self.client.post(reverse('accounts:signup'), self.data)
        self.assertRedirects(r, reverse('accounts:signup_done'))
        account = Account.objects.get()
        self.assertEqual((account.name, account.country, account.currency, account.is_active, account.max_shops),
                         ('Diallo & Fils', 'GM', 'GMD', False, 1))
        self.assertEqual(account.status, 'pending')
        shop = account.shops.get()
        self.assertEqual((shop.name, shop.code), ('Serrekunda', 'SER'))
        manager = User.objects.get(username='aliou')
        self.assertEqual((manager.role, manager.account, manager.shop), ('manager', account, None))
        self.assertEqual(AppSetting.for_account(account).company_name, 'Diallo & Fils')

        # Bon mot de passe, mais compte pas encore activé : refusé avec un message clair.
        r = login(self.client, manager, self.data['password1'])
        self.assertContains(r, "attente d&#x27;activation")
        self.assertNotIn('_auth_user_id', self.client.session)

        services.extend(account, 1)
        r = login(self.client, manager, self.data['password1'])
        self.assertRedirects(r, reverse('pos'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)

    def test_signup_validation(self):
        make_account()
        User.objects.create_user('pris', password=PASSWORD)
        r = self.client.post(reverse('accounts:signup'), {**self.data, 'username': 'PRIS', 'password2': 'autre'})
        self.assertContains(r, 'déjà pris')
        self.assertContains(r, 'ne correspondent pas')
        self.assertEqual(Account.objects.count(), 1)

    def test_bots_are_silently_ignored(self):
        r = self.client.post(reverse('accounts:signup'), {**self.data, 'website': 'http://spam'})
        self.assertRedirects(r, reverse('accounts:signup_done'))
        self.assertFalse(Account.objects.exists())

    def test_login_page_links_to_signup(self):
        self.assertContains(self.client.get(reverse('users:login')), reverse('accounts:signup'))


class SubscriptionTests(TestCase):
    def setUp(self):
        self.account, (self.shop,), self.manager = make_account()
        self.employee = make_employee(self.shop, 'awa')
        self.today = timezone.localdate()

    def test_status_and_days_left(self):
        a = self.account
        self.assertEqual((a.status, a.days_left, a.is_open), ('active', None, True))
        a.active_until = self.today + datetime.timedelta(days=3)
        self.assertEqual((a.status, a.days_left), ('soon', 3))
        a.active_until = self.today
        self.assertTrue(a.is_open)                       # le dernier jour est inclus
        a.active_until = self.today - datetime.timedelta(days=1)
        self.assertEqual((a.status, a.is_open), ('expired', False))
        a.is_active = False
        self.assertEqual(a.status, 'suspended')

    def test_expired_account_is_logged_out_on_next_page(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)
        Account.objects.filter(pk=self.account.pk).update(active_until=self.today - datetime.timedelta(days=1))
        r = self.client.get(reverse('order_list'))
        self.assertRedirects(r, reverse('users:login'))
        self.assertNotIn('_auth_user_id', self.client.session)
        r = login(self.client, self.employee)
        self.assertContains(r, 'pris fin')

    def test_suspended_account_cannot_log_in(self):
        Account.objects.filter(pk=self.account.pk).update(is_active=False, active_until=self.today)
        self.assertContains(login(self.client, self.manager), 'suspendu')
        self.client.force_login(self.manager)
        self.assertRedirects(self.client.get(reverse('dashboard')), reverse('users:login'))

    def test_expiry_banner_for_manager_only(self):
        Account.objects.filter(pk=self.account.pk).update(active_until=self.today + datetime.timedelta(days=5))
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('order_list')), 'dans <b>5 jours</b>')
        self.client.force_login(self.employee)
        self.assertNotContains(self.client.get(reverse('order_list')), 'abonnement')
        Account.objects.filter(pk=self.account.pk).update(active_until=self.today + datetime.timedelta(days=30))
        self.client.force_login(self.manager)
        self.assertNotContains(self.client.get(reverse('order_list')), 'abonnement')

    def test_extend(self):
        self.assertEqual(services.add_months(datetime.date(2026, 1, 31), 1), datetime.date(2026, 2, 28))
        self.assertEqual(services.add_months(datetime.date(2026, 11, 15), 3), datetime.date(2027, 2, 15))
        # Compte encore ouvert : on prolonge depuis sa date de fin, sans perdre de jours.
        self.account.active_until = self.today + datetime.timedelta(days=10)
        self.account.save()
        end = services.extend(self.account, 1)
        self.assertEqual(end, services.add_months(self.today + datetime.timedelta(days=10), 1))
        # Compte expiré : on repart d'aujourd'hui (1 mois = jusqu'à la veille du même jour le mois suivant).
        self.account.active_until = self.today - datetime.timedelta(days=40)
        self.account.save()
        end = services.extend(self.account, 1)
        self.assertEqual(end, services.add_months(self.today - datetime.timedelta(days=1), 1))
        self.assertTrue(self.account.is_open)

    def test_single_manager_per_account(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create_user('chef2', password=PASSWORD, role='manager', account=self.account)


class AccountIsolationTests(TestCase):
    """Deux entreprises clientes ne voient jamais les données l'une de l'autre."""

    @classmethod
    def setUpTestData(cls):
        cls.a, (cls.shop_a,), cls.manager_a = make_account('Alpha')
        cls.b, (cls.shop_b,), cls.manager_b = make_account('Bravo', currency='GMD', country='GM')
        cls.product_a = Product.objects.create(account=cls.a, title='Riz Alpha', value=D('25000'))
        cls.product_b = Product.objects.create(account=cls.b, title='Riz Bravo', value=D('900'))
        adjust_stock(cls.product_a.pk, 'add', 10, shop=cls.shop_a)
        adjust_stock(cls.product_b.pk, 'add', 10, shop=cls.shop_b)
        cls.client_b = Client.objects.create(shop=cls.shop_b, name='Client Bravo', phone='7000001')
        cls.order_b = checkout(lines=[{'product_id': cls.product_b.pk, 'qty': 1}], user=cls.manager_b,
                               shop=cls.shop_b, method='cash').order

    def setUp(self):
        self.client.force_login(self.manager_a)

    def test_lists_show_only_own_data(self):
        self.assertNotContains(self.client.get(reverse('product:product_list')), 'Riz Bravo')
        self.assertContains(self.client.get(reverse('product:product_list')), 'Riz Alpha')
        self.assertNotContains(self.client.get(reverse('client:client_list')), 'Client Bravo')
        self.assertNotContains(self.client.get(reverse('order_list')), self.order_b.title)
        catalog = self.client.get(reverse('api_catalog')).json()
        self.assertEqual([row[1] for row in catalog['products']], ['Riz Alpha'])
        self.assertEqual(catalog['currency'], 'GNF')
        self.assertEqual(self.client.get(reverse('dashboard')).context['sales']['count'], 0)

    def test_other_account_objects_are_unreachable(self):
        for url in (reverse('order_detail', args=[self.order_b.pk]), reverse('order_ticket', args=[self.order_b.pk]),
                    reverse('invoice_pdf', args=[self.order_b.pk]), reverse('client:client_detail', args=[self.client_b.pk]),
                    reverse('product:edit_product', args=[self.product_b.pk]),
                    reverse('product:quick_stock', args=[self.product_b.pk]),
                    reverse('accounts:shop_edit', args=[self.shop_b.pk]),
                    reverse('users:user_update', args=[self.manager_b.pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        r = self.client.post(reverse('order_cancel', args=[self.order_b.pk]))
        self.assertEqual(r.status_code, 404)
        self.assertTrue(Order.objects.filter(pk=self.order_b.pk).exists())

    def test_services_refuse_other_account_products(self):
        with self.assertRaises(SaleError):
            checkout(lines=[{'product_id': self.product_b.pk, 'qty': 1}], user=self.manager_a, shop=self.shop_a,
                     method='cash')
        with self.assertRaises(StockError):
            receive([{'product_id': self.product_b.pk, 'qty': 5, 'unit_cost': '100'}], user=self.manager_a,
                    shop=self.shop_a)
        with self.assertRaises(StockError):
            adjust_stock(self.product_b.pk, 'add', 5, shop=self.shop_a)
        with self.assertRaises(SaleError):     # client d'une autre boutique
            checkout(lines=[{'product_id': self.product_a.pk, 'qty': 1}], user=self.manager_a, shop=self.shop_a,
                     method='credit', client_id=self.client_b.pk)
        self.assertEqual(stock_qty(self.shop_b, self.product_b), 9)

    def test_same_names_allowed_in_different_accounts(self):
        Product.objects.create(account=self.b, title='Riz Alpha', value=D('1'))
        Client.objects.create(shop=self.shop_a, name='Homonyme', phone='7000001')
        r = self.client.post(reverse('product:add_product'), {'title': 'Riz Bravo', 'value': '100', 'active': 'on'})
        self.assertRedirects(r, reverse('product:product_list'))

    def test_settings_are_per_account(self):
        self.client.post(reverse('users:app_settings'), {
            'company_name': 'Alpha SARL', 'company_tagline': '', 'low_stock_threshold': 3, 'signatory_name': '',
            'brand_color_primary': '#000000', 'brand_color_secondary': '#111111', 'brand_color_accent': '#222222'})
        self.assertEqual(AppSetting.for_account(self.a).company_name, 'Alpha SARL')
        self.assertEqual(AppSetting.for_account(self.b).company_name, 'Bravo')
        self.client.force_login(self.manager_b)
        r = self.client.get(reverse('order_list'))
        self.assertContains(r, 'Bravo')
        self.assertNotContains(r, 'Alpha SARL')


class ShopTests(TestCase):
    """Un compte, deux boutiques : chaque employé reste dans la sienne, le gérant voit tout."""

    @classmethod
    def setUpTestData(cls):
        cls.account, (cls.kaloum, cls.matoto), cls.manager = make_account('Kalma', shops=('Kaloum', 'Matoto'),
                                                                          max_shops=3)
        cls.emp_k = make_employee(cls.kaloum, 'awa')
        cls.emp_m = make_employee(cls.matoto, 'binta')
        cls.riz = Product.objects.create(account=cls.account, title='Riz', value=D('25000'), prix_achat=D('20000'))
        adjust_stock(cls.riz.pk, 'add', 10, shop=cls.kaloum)
        adjust_stock(cls.riz.pk, 'add', 4, shop=cls.matoto)
        cls.client_m = Client.objects.create(shop=cls.matoto, name='Cliente Matoto', phone='622000002')
        cls.order_k = checkout(lines=[{'product_id': cls.riz.pk, 'qty': 2}], user=cls.emp_k, shop=cls.kaloum,
                               method='cash').order
        cls.order_m = checkout(lines=[{'product_id': cls.riz.pk, 'qty': 1}], user=cls.emp_m, shop=cls.matoto,
                               method='credit', client_id=cls.client_m.pk).order

    def test_stock_and_numbering_per_shop(self):
        self.assertEqual((stock_qty(self.kaloum, self.riz), stock_qty(self.matoto, self.riz)), (8, 3))
        self.assertEqual((self.kaloum.code, self.order_k.title), ('KAL', 'KAL-000001'))
        self.assertEqual(self.order_m.title, 'MAT-000001')
        nxt = checkout(lines=[{'product_id': self.riz.pk, 'qty': 1}], user=self.emp_k, shop=self.kaloum,
                       method='cash').order
        self.assertEqual(nxt.title, 'KAL-000002')
        with self.assertRaises(SaleError):     # Matoto n'a plus que 3 sacs
            checkout(lines=[{'product_id': self.riz.pk, 'qty': 4}], user=self.emp_m, shop=self.matoto, method='cash')

    def test_employee_sees_only_his_shop(self):
        self.client.force_login(self.emp_k)
        r = self.client.get(reverse('order_list'))
        self.assertContains(r, 'KAL-000001')
        self.assertNotContains(r, 'MAT-000001')
        self.assertNotContains(r, 'shop-switch')              # pas de sélecteur de boutique
        self.assertEqual(self.client.get(reverse('order_detail', args=[self.order_m.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse('client:client_detail', args=[self.client_m.pk])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('client:client_list')), 'Cliente Matoto')
        catalog = self.client.get(reverse('api_catalog')).json()
        self.assertEqual(catalog['products'][0][4], 8)       # stock de Kaloum
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)
        # Il ne peut pas changer de boutique.
        self.client.post(reverse('accounts:switch_shop'), {'shop': self.matoto.pk})
        self.assertNotContains(self.client.get(reverse('order_list')), 'MAT-000001')

    def test_employee_receives_goods_in_his_shop(self):
        self.client.force_login(self.emp_m)
        r = self.client.post(reverse('product:api_receive'),
                             '{"lines": [{"product_id": %d, "qty": 5, "unit_cost": "20000"}]}' % self.riz.pk,
                             content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((stock_qty(self.kaloum, self.riz), stock_qty(self.matoto, self.riz)), (8, 8))
        depense = Depense.objects.get(type_depense__nom='Approvisionnement')
        self.assertEqual((depense.account, depense.shop), (self.account, self.matoto))

    def test_manager_overview_and_switch(self):
        self.client.force_login(self.manager)
        ctx = self.client.get(reverse('dashboard')).context
        self.assertTrue(ctx['scope'].all_shops)
        self.assertEqual(ctx['sales']['total'], D('75000'))
        self.assertEqual({r['shop'].code: r['total'] for r in ctx['by_shop']}, {'KAL': D('50000'), 'MAT': D('25000')})
        self.assertEqual(ctx['unpaid_total'], D('25000'))
        # Stock en vue d'ensemble : total des boutiques, et la caisse demande une boutique.
        self.assertContains(self.client.get(reverse('product:product_list')), '(total)')
        r = self.client.get(reverse('pos'))
        self.assertTemplateUsed(r, 'accounts/choose_shop.html')
        self.assertEqual(self.client.get(reverse('api_catalog')).status_code, 409)

        r = self.client.post(reverse('accounts:switch_shop'), {'shop': self.matoto.pk, 'next': reverse('dashboard')})
        self.assertRedirects(r, reverse('dashboard'))
        ctx = self.client.get(reverse('dashboard')).context
        self.assertEqual((ctx['scope'].shop, ctx['sales']['total'], ctx['by_shop']), (self.matoto, D('25000'), None))
        self.assertEqual(self.client.get(reverse('pos')).status_code, 200)
        self.assertEqual(self.client.get(reverse('api_catalog')).json()['products'][0][4], 3)
        # Le gérant ouvre une vente de n'importe quelle boutique.
        self.assertEqual(self.client.get(reverse('order_detail', args=[self.order_k.pk])).status_code, 200)

    def test_common_expenses_count_only_in_overview(self):
        loyer = TypeDepense.objects.create(account=self.account, nom='Loyer')
        Depense.objects.create(account=self.account, shop=self.kaloum, type_depense=loyer, description='Loyer K',
                               montant=D('1000'))
        Depense.objects.create(account=self.account, shop=None, type_depense=loyer, description='Salaire gérant',
                               montant=D('5000'))
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse('dashboard')).context['other_total'], D('6000'))
        self.client.post(reverse('accounts:switch_shop'), {'shop': self.kaloum.pk})
        self.assertEqual(self.client.get(reverse('dashboard')).context['other_total'], D('1000'))

    def test_expense_form_offers_common(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('aprovision:nouvelle_depense'), {
            'new_type': 'Transport', 'montant': '3000', 'date_depense': '2026-10-01', 'description': 'Taxi',
            'where': 'common'})
        self.assertRedirects(r, reverse('aprovision:depense_list'))
        d = Depense.objects.get(description='Taxi')
        self.assertEqual((d.account, d.shop, d.type_depense.account), (self.account, None, self.account))

    def test_low_stock_overview_names_the_shop(self):
        self.client.force_login(self.manager)
        low = self.client.get(reverse('dashboard')).context['low_stock']   # seuil 5 : Matoto (3) en manque
        self.assertEqual([p.title for p in low], ['Riz'])
        self.assertEqual([(s.code, q) for s, q in low[0].low_shops], [('MAT', 3)])

    def test_shop_limit_and_creation(self):
        self.client.force_login(self.manager)
        r = self.client.post(reverse('accounts:shop_create'), {'name': 'Madina', 'code': '', 'address': 'Marché'})
        self.assertRedirects(r, reverse('accounts:shop_list'))
        madina = Shop.objects.get(name='Madina')
        self.assertEqual((madina.account, madina.code), (self.account, 'MAD'))
        r = self.client.get(reverse('accounts:shop_create'))           # 3 / 3 : limite atteinte
        self.assertRedirects(r, reverse('accounts:shop_list'))
        self.assertContains(self.client.get(reverse('accounts:shop_list')), 'toutes les boutiques de votre abonnement')
        r = self.client.post(reverse('accounts:shop_edit', args=[madina.pk]), {'name': 'Madina', 'code': 'kal'})
        self.assertContains(r, 'déjà utilisé')

    def test_employee_creation_bound_to_a_shop(self):
        other_account, (other_shop,), _ = make_account('Autre')
        self.client.force_login(self.manager)
        data = {'username': 'fanta', 'first_name': 'Fanta', 'password1': 'un-mot-de-passe-solide',
                'password2': 'un-mot-de-passe-solide'}
        r = self.client.post(reverse('users:user_create'), {**data, 'shop': other_shop.pk})
        self.assertEqual(r.status_code, 200)                           # boutique d'un autre compte refusée
        r = self.client.post(reverse('users:user_create'), {**data, 'shop': self.matoto.pk})
        self.assertRedirects(r, reverse('users:user_list'))
        fanta = User.objects.get(username='fanta')
        self.assertEqual((fanta.role, fanta.account, fanta.shop), ('employee', self.account, self.matoto))

    def test_store_keys_differ_per_shop(self):
        self.client.force_login(self.emp_k)
        key_k = self.client.get(reverse('pos')).context['scope'].store_key()
        self.client.force_login(self.emp_m)
        key_m = self.client.get(reverse('pos')).context['scope'].store_key()
        self.assertNotEqual(key_k, key_m)


class OwnerAdminTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_superuser('proprio', 'p@example.com', PASSWORD)
        self.client.force_login(self.owner)
        self.account, (self.shop,), self.manager = make_account('Client')
        Account.objects.filter(pk=self.account.pk).update(is_active=False, active_until=None)   # en attente

    def test_owner_is_sent_to_admin(self):
        self.assertRedirects(self.client.get(reverse('pos')), reverse('admin:index'))
        self.assertEqual(self.client.get(reverse('admin:accounts_account_changelist')).status_code, 200)
        r = self.client.get(reverse('admin:accounts_account_changelist'), {'statut': 'pending'})
        self.assertContains(r, 'Client')

    def test_activate_action(self):
        r = self.client.post(reverse('admin:accounts_account_changelist'),
                             {'action': 'activate_3', '_selected_action': [self.account.pk]})
        self.assertEqual(r.status_code, 302)
        self.account.refresh_from_db()
        self.assertTrue(self.account.is_open)
        self.assertEqual(self.account.active_until,
                         services.add_months(timezone.localdate() - datetime.timedelta(days=1), 3))

    def test_delete_with_all_data(self):
        Account.objects.filter(pk=self.account.pk).update(is_active=True)
        product = Product.objects.create(account=self.account, title='Riz', value=D('1000'))
        adjust_stock(product.pk, 'add', 3, shop=self.shop)
        customer = Client.objects.create(shop=self.shop, name='X', phone='6220000')
        checkout(lines=[{'product_id': product.pk, 'qty': 1}], user=self.manager, shop=self.shop, method='credit',
                 client_id=customer.pk)
        url = reverse('admin:accounts_account_changelist')
        payload = {'action': 'delete_with_data', '_selected_action': [self.account.pk]}
        self.assertContains(self.client.post(url, payload), 'SUPPRIMER')
        self.client.post(url, {**payload, 'confirm': 'non'})
        self.assertTrue(Account.objects.filter(pk=self.account.pk).exists())
        self.client.post(url, {**payload, 'confirm': 'SUPPRIMER'})
        self.assertFalse(Account.objects.filter(pk=self.account.pk).exists())
        for qs in (Shop.objects.all(), Product.objects.all(), Order.objects.all(), Client.objects.all(),
                   User.objects.exclude(pk=self.owner.pk)):
            with self.subTest(model=qs.model.__name__):
                self.assertFalse(qs.exists())
