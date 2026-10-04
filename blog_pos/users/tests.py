from django.test import TestCase
from django.urls import reverse

from .middleware import SetupMiddleware
from .models import AppSetting, User


class AppSettingsColorsTests(TestCase):
    def setUp(self):
        SetupMiddleware.setup_done = False
        self.manager = User.objects.create_user('chef', password='x' * 10, role='manager')
        self.client.force_login(self.manager)

    def post(self, **colors):
        data = {'company_name': 'Boutique', 'company_tagline': '', 'currency_label': 'GNF',
                'low_stock_threshold': 5, 'signatory_name': '',
                'brand_color_primary': '#0e6dfa', 'brand_color_secondary': '#1b8650',
                'brand_color_accent': '#fbc105'}
        data.update(colors)
        return self.client.post(reverse('users:app_settings'), data)

    def test_three_colors_are_saved(self):
        r = self.post(brand_color_primary='#0E6DFA')
        self.assertRedirects(r, reverse('users:app_settings'))
        s = AppSetting.get_solo()
        self.assertEqual((s.brand_color_primary, s.brand_color_secondary, s.brand_color_accent),
                         ('#0e6dfa', '#1b8650', '#fbc105'))

    def test_invalid_color_is_refused(self):
        r = self.post(brand_color_accent='rouge')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Couleur invalide')
        self.assertNotEqual(AppSetting.get_solo().brand_color_accent, 'rouge')

    def test_page_shows_three_color_fields(self):
        r = self.client.get(reverse('users:app_settings'))
        for name in ('brand_color_primary', 'brand_color_secondary', 'brand_color_accent'):
            self.assertContains(r, f'name="{name}"')
