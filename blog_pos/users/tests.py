import re

from django.core import mail
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.testing import PASSWORD, make_account, make_employee
from .models import AppSetting


class AppSettingsColorsTests(TestCase):
    def setUp(self):
        self.account, _, self.manager = make_account()
        self.client.force_login(self.manager)

    def settings(self):
        return AppSetting.for_account(self.account)

    def post(self, **colors):
        data = {'company_name': 'Boutique', 'company_tagline': '',
                'low_stock_threshold': 5, 'signatory_name': '',
                'brand_color_primary': '#0e6dfa', 'brand_color_secondary': '#1b8650',
                'brand_color_accent': '#fbc105'}
        data.update(colors)
        return self.client.post(reverse('users:app_settings'), data)

    def test_three_colors_are_saved(self):
        r = self.post(brand_color_primary='#0E6DFA')
        self.assertRedirects(r, reverse('users:app_settings'))
        s = self.settings()
        self.assertEqual((s.brand_color_primary, s.brand_color_secondary, s.brand_color_accent),
                         ('#0e6dfa', '#1b8650', '#fbc105'))

    def test_invalid_color_is_refused(self):
        r = self.post(brand_color_accent='rouge')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Couleur invalide')
        self.assertNotEqual(self.settings().brand_color_accent, 'rouge')

    def test_page_shows_three_color_fields(self):
        r = self.client.get(reverse('users:app_settings'))
        for name in ('brand_color_primary', 'brand_color_secondary', 'brand_color_accent'):
            self.assertContains(r, f'name="{name}"')

    def test_currency_comes_from_the_account(self):
        """Un compte = un pays = une devise : elle s'affiche mais ne se change pas dans les paramètres."""
        r = self.client.get(reverse('users:app_settings'))
        self.assertNotContains(r, 'name="currency_label"')
        self.assertContains(r, 'GNF')
        self.post(currency_label='EUR')
        self.account.refresh_from_db()
        self.assertEqual(self.account.currency, 'GNF')


class ForgotPasswordTests(TestCase):
    """Mot de passe oublié : un lien par email, utilisable une fois, pour choisir un nouveau mot de passe."""

    def setUp(self):
        cache.clear()
        self.account, (self.shop,), self.manager = make_account('Kalma')
        self.employee = make_employee(self.shop, 'awa', email='awa@example.com')

    def ask(self, identifier):
        return self.client.post(reverse('users:forgot_password'), {'identifier': identifier})

    def link_from_mail(self):
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['awa@example.com'])
        self.assertIn('Kalma', msg.subject)
        self.assertIn('awa', msg.body)
        self.assertTrue(msg.alternatives)                       # version HTML avec bouton
        return re.search(r'http://testserver(/users/reset/\S+/)', msg.body).group(1)

    def test_full_reset_by_email_link(self):
        r = self.ask('AWA@example.com')                         # email ou identifiant, sans souci de casse
        self.assertRedirects(r, reverse('users:forgot_password_sent'))
        link = self.link_from_mail()
        r = self.client.get(link)
        self.assertContains(r, 'Nouveau mot de passe')
        r = self.client.post(link, {'new_password1': 'nouveau-mot-de-passe', 'new_password2': 'nouveau-mot-de-passe'})
        self.assertRedirects(r, reverse('users:login'))
        self.assertFalse(self.client.login(username='awa', password=PASSWORD))
        self.assertTrue(self.client.login(username='awa', password='nouveau-mot-de-passe'))
        self.client.logout()
        # Le lien ne sert qu'une fois.
        self.assertContains(self.client.get(link), 'Lien expiré')

    def test_username_works_too_and_mismatch_is_refused(self):
        self.ask('awa')
        link = self.link_from_mail()
        r = self.client.post(link, {'new_password1': 'nouveau-mot-de-passe', 'new_password2': 'autre-chose-123'})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(self.client.login(username='awa', password=PASSWORD))

    def test_unknown_or_no_email_gives_same_answer_without_mail(self):
        for identifier in ('inconnu', self.manager.username):  # le gérant n'a pas d'email
            with self.subTest(identifier=identifier):
                self.assertRedirects(self.ask(identifier), reverse('users:forgot_password_sent'))
        self.assertEqual(len(mail.outbox), 0)

    def test_bad_links(self):
        self.assertContains(self.client.get(reverse('users:reset_password', args=['xx', 'yy'])), 'Lien expiré')
        self.ask('awa')
        link = self.link_from_mail()
        self.assertContains(self.client.get(link[:-3] + 'zz/'), 'Lien expiré')

    def test_requests_are_limited(self):
        for _ in range(5):
            self.ask('inconnu')
        self.assertEqual(self.ask('awa').status_code, 429)
        self.assertEqual(len(mail.outbox), 0)

