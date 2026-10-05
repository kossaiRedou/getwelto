from django.test import TestCase
from django.urls import reverse

from core.testing import make_account
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
