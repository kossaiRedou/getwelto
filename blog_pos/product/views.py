import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import shop_required
from aprovision.services import StockError, adjust_stock, receive, restock
from core.decorators import api_login_required, manager_required
from core.utils import fix_scanned_code, json_etag_response, to_cents
from .forms import CategoryForm, ProductForm, StockForm
from .models import DEFAULT_CATEGORY_COLOR, Stock


@login_required
def product_list(request):
    scope = request.scope
    products = scope.products_with_qty().select_related('category')
    q = request.GET.get('q', '').strip()
    if q:
        code = fix_scanned_code(q)
        products = products.filter(Q(title__icontains=q) | Q(barcode=code) | Q(category__title__icontains=q))
    category = request.GET.get('category', '')
    if category.isdigit():
        products = products.filter(category_id=category)
    threshold = scope.settings().low_stock_threshold
    status = request.GET.get('status', '')
    if status == 'low':
        products = scope.low_stock(products.filter(active=True), threshold)
    elif status == 'inactive':
        products = products.filter(active=False)
    elif status != 'all':
        products = products.filter(active=True)

    page = Paginator(products.order_by('title'), 50).get_page(request.GET.get('page'))
    return render(request, 'product/list.html', {
        'page_obj': page,
        'categories': scope.categories(),
        'q': q,
        'category': category,
        'status': status,
        'threshold': threshold,
        'low_count': scope.low_stock(scope.products_with_qty().filter(active=True), threshold).count(),
    })


@manager_required
def product_create(request):
    scope = request.scope
    form = ProductForm(request.POST or None, account=scope.account, shop=scope.shop)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            initial = form.cleaned_data.get('initial_qty') or 0
            if initial > 0 and scope.shop:
                adjust_stock(product.pk, 'add', initial, shop=scope.shop, user=request.user,
                             description='Stock initial')
        messages.success(request, f'Produit « {product.title} » ajouté.')
        if 'again' in request.POST:
            return redirect('product:add_product')
        return redirect('product:product_list')
    return render(request, 'product/form.html', {'form': form, 'title': 'Nouveau produit'})


@manager_required
def product_edit(request, pk):
    product = get_object_or_404(request.scope.products(), pk=pk)
    form = ProductForm(request.POST or None, instance=product, account=request.scope.account)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Produit « {product.title} » modifié.')
        return redirect('product:product_list')
    return render(request, 'product/form.html', {
        'form': form, 'product': product, 'title': f'Modifier « {product.title} »',
        'stock_rows': request.scope.stock_by_shop([product.pk])[product.pk],
    })


def _shop_qty(shop, product):
    return Stock.objects.filter(shop=shop, product=product).values_list('qty', flat=True).first() or 0


@manager_required
@shop_required
def product_stock(request, pk):
    scope = request.scope
    product = get_object_or_404(scope.products(), pk=pk)
    form = StockForm(request.POST or None, initial={'unit_cost': product.prix_achat or None})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            if d['action'] == 'restock':
                restock(product.pk, d['quantity'], d['unit_cost'], shop=scope.shop, user=request.user,
                        fournisseur=d['fournisseur'], description=d['description'])
            else:
                adjust_stock(product.pk, d['action'], d['quantity'], shop=scope.shop, user=request.user,
                             description=d['description'])
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f'Stock de « {product.title} » à {scope.shop} : {_shop_qty(scope.shop, product)}.')
            return redirect('product:product_list')
    product.qty = _shop_qty(scope.shop, product)
    movements = scope.movements().filter(produit=product).select_related('created_by')[:15]
    return render(request, 'product/stock.html', {'form': form, 'product': product, 'movements': movements})


@require_POST
@manager_required
def product_toggle(request, pk):
    product = get_object_or_404(request.scope.products(), pk=pk)
    product.active = not product.active
    product.save(update_fields=['active', 'updated_at'])
    messages.success(request, f'« {product.title} » {"remis en vente" if product.active else "retiré de la vente"}.')
    return redirect(request.POST.get('next') or 'product:product_list')


@manager_required
def product_delete(request, pk):
    product = get_object_or_404(request.scope.products(), pk=pk)
    if request.method == 'POST':
        try:
            product.delete()
        except ProtectedError:
            messages.error(request, f'« {product.title} » a déjà été vendu : il ne peut pas être supprimé. '
                                    'Retirez-le de la vente à la place.')
        else:
            messages.success(request, f'Produit « {product.title} » supprimé.')
        return redirect('product:product_list')
    return render(request, 'core/confirm.html', {
        'title': 'Supprimer le produit',
        'message': f'Supprimer définitivement « {product.title} » ?',
        'cancel_url': 'product:product_list',
    })


@manager_required
def category_management(request):
    scope = request.scope
    scope.default_category()
    form = CategoryForm(request.POST or None, account=scope.account)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'Catégorie « {category.title} » créée.')
        return redirect('product:category_management')
    categories = scope.categories().annotate(n=Count('product')).order_by('-is_default', 'title')
    return render(request, 'product/categories.html', {'form': form, 'categories': categories})


@manager_required
def category_edit(request, pk):
    category = get_object_or_404(request.scope.categories(), pk=pk)
    form = CategoryForm(request.POST or None, instance=category, account=request.scope.account)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Catégorie « {category.title} » modifiée.')
        return redirect('product:category_management')
    return render(request, 'product/category_form.html', {'form': form, 'category': category})


@require_POST
@manager_required
def category_delete(request, pk):
    scope = request.scope
    category = get_object_or_404(scope.categories(), pk=pk)
    if category.is_default:
        messages.error(request, f'La catégorie « {category.title} » ne peut pas être supprimée : '
                                'elle accueille les produits sans catégorie.')
        return redirect('product:category_management')
    default = scope.default_category()
    with transaction.atomic():
        moved = scope.products().filter(category=category).update(category=default, updated_at=timezone.now())
        category.delete()
    messages.success(request, f'Catégorie « {category.title} » supprimée'
                              + (f' : {moved} produit{"s" if moved > 1 else ""} déplacé{"s" if moved > 1 else ""} '
                                 f'dans « {default.title} ».' if moved else '.'))
    return redirect('product:category_management')


# ---------------------------------------------------------------- Approvisionnement (réception)

@login_required
@shop_required
def restock_page(request):
    request.scope.default_category()
    return render(request, 'product/restock.html', {'categories': request.scope.categories()})


@require_GET
@api_login_required
@shop_required
def api_stock_catalog(request):
    """Catalogue de la réception : tous les produits (même retirés de la vente), stock de la boutique."""
    scope = request.scope
    rows = scope.products_with_qty().order_by('title').values_list(
        'id', 'title', 'barcode', 'value', 'qty', 'category_id', 'prix_achat', 'active', 'discount_value',
        'color', 'category__color')
    return json_etag_response(request, {
        'currency': scope.account.currency,
        'products': [[pid, title, barcode or '', to_cents(value), qty, cat or 0, to_cents(cost),
                      1 if active else 0, to_cents(promo), color or cat_color or DEFAULT_CATEGORY_COLOR]
                     for pid, title, barcode, value, qty, cat, cost, active, promo, color, cat_color in rows],
        'categories': list(scope.categories().values_list('id', 'title', 'color')),
    })


@require_POST
@api_login_required
@shop_required
def api_receive(request):
    try:
        payload = json.loads(request.body or b'{}')
        key = uuid.UUID(str(payload['key'])) if payload.get('key') else None
    except (ValueError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)
    try:
        result = receive(payload.get('lines'), user=request.user, shop=request.scope.shop, key=key,
                         fournisseur=str(payload.get('fournisseur') or ''),
                         reference=str(payload.get('reference') or ''),
                         can_set_price=request.scope.is_manager)
    except StockError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if result is None:
        return JsonResponse({'ok': True, 'replayed': True})
    return JsonResponse({'ok': True, 'replayed': False, 'lines': result['lines'], 'units': result['units'],
                         'created': result['created'], 'total': to_cents(result['total'])})
