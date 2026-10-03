from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from users.middleware import SetupMiddleware
from users.models import User
from .models import DEFAULT_CATEGORY_COLOR, PALETTE, Category, Product, initials


class ColorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('chef', password='x' * 10, role='manager', first_name='Chef')

    def setUp(self):
        SetupMiddleware.setup_done = False
        self.client.force_login(self.manager)

    def test_product_without_category_goes_to_autres(self):
        p = Product.objects.create(title='Bougie', value=Decimal('500'))
        self.assertEqual(p.category.title, 'Autres')
        self.assertTrue(p.category.is_default)
        self.assertEqual(p.display_color, DEFAULT_CATEGORY_COLOR)
        self.assertEqual(Category.objects.filter(is_default=True).count(), 1)

    def test_categories_get_distinct_palette_colors(self):
        colors = [Category.objects.create(title=f'Cat {i}').color for i in range(len(PALETTE))]
        self.assertEqual(sorted(colors), sorted(c for c, _ in PALETTE))

    def test_product_color_overrides_category(self):
        cat = Category.objects.create(title='Boissons', color='#2563eb')
        p = Product.objects.create(title='Coca', value=Decimal('2000'), category=cat)
        self.assertEqual(p.display_color, '#2563eb')
        p.color = '#DC2626'
        p.save()
        self.assertEqual(p.display_color, '#dc2626')

    def test_initials(self):
        self.assertEqual(initials('Coca-Cola 1L'), 'CC')
        self.assertEqual(initials('Riz 5kg'), 'R5')
        self.assertEqual(initials('savon'), 'S')
        self.assertEqual(initials(''), '?')

    def test_delete_category_moves_products_to_autres(self):
        cat = Category.objects.create(title='Boissons')
        p = Product.objects.create(title='Coca', value=Decimal('2000'), category=cat)
        self.client.post(reverse('product:delete_category', args=[cat.pk]))
        self.assertFalse(Category.objects.filter(pk=cat.pk).exists())
        p.refresh_from_db()
        self.assertTrue(p.category.is_default)

    def test_default_category_cannot_be_deleted(self):
        default = Category.get_default()
        self.client.post(reverse('product:delete_category', args=[default.pk]))
        self.assertTrue(Category.objects.filter(pk=default.pk).exists())

    def test_category_form_create_and_edit(self):
        r = self.client.post(reverse('product:category_management'), {'title': 'Boissons', 'color': '#16a34a'})
        self.assertRedirects(r, reverse('product:category_management'))
        cat = Category.objects.get(title='Boissons')
        self.assertEqual(cat.color, '#16a34a')
        r = self.client.post(reverse('product:edit_category', args=[cat.pk]), {'title': 'Boissons', 'color': '#dc2626'})
        self.assertRedirects(r, reverse('product:category_management'))
        cat.refresh_from_db()
        self.assertEqual(cat.color, '#dc2626')
        r = self.client.post(reverse('product:edit_category', args=[cat.pk]), {'title': 'Boissons', 'color': 'red'})
        self.assertEqual(r.status_code, 200)

    def test_product_form_color(self):
        data = {'title': 'Riz', 'value': '25000', 'category': Category.get_default().pk, 'active': 'on'}
        r = self.client.post(reverse('product:add_product'), {**data, 'color': '#ea580c'})
        self.assertRedirects(r, reverse('product:product_list'))
        self.assertEqual(Product.objects.get(title='Riz').color, '#ea580c')
        r = self.client.post(reverse('product:add_product'), {**data, 'title': 'Mil', 'color': ''})
        self.assertEqual(Product.objects.get(title='Mil').color, '')
        r = self.client.post(reverse('product:add_product'), {**data, 'title': 'Sel', 'color': 'javascript:x'})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Product.objects.filter(title='Sel').exists())

    def test_pages_render(self):
        Product.objects.create(title='Coca', value=Decimal('2000'))
        for url in (reverse('product:category_management'), reverse('product:product_list'),
                    reverse('product:add_product'), reverse('product:edit_category', args=[Category.get_default().pk])):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)

    def test_catalogs_include_colors(self):
        cat = Category.objects.create(title='Boissons', color='#2563eb')
        Product.objects.create(title='Coca', value=Decimal('2000'), category=cat)
        Product.objects.create(title='Fanta', value=Decimal('2000'), category=cat, color='#ea580c')
        data = self.client.get(reverse('api_catalog')).json()
        colors = {row[1]: row[6] for row in data['products']}
        self.assertEqual(colors, {'Coca': '#2563eb', 'Fanta': '#ea580c'})
        self.assertIn([cat.pk, 'Boissons', '#2563eb'], data['categories'])
        stock = self.client.get(reverse('product:api_stock_catalog')).json()
        self.assertEqual({row[1]: row[9] for row in stock['products']}, colors)


class TextColorTests(TestCase):
    def test_text_color_is_darker_shade_of_display_color(self):
        from .models import text_on_light
        cat = Category.objects.create(title='Boissons', color='#2563eb')
        p = Product.objects.create(title='Coca', value=Decimal('2000'), category=cat)
        self.assertEqual(p.text_color, text_on_light('#2563eb'))
        self.assertEqual(text_on_light('#ffffff', 0.5), '#808080')
        p.color = '#dc2626'
        self.assertEqual(p.text_color, text_on_light('#dc2626'))
