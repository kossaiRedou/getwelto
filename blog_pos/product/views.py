import json
import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from aprovision.models import MouvementStock
from aprovision.services import StockError, adjust_stock, receive, restock
from core.decorators import api_manager_required, manager_required
from core.utils import json_etag_response, to_cents
from users.models import AppSetting
from .forms import CategoryForm, ProductForm, StockForm
from .models import Category, Product, get_low_stock_threshold


@login_required
def product_list(request):
    products = Product.objects.select_related('category')
    q = request.GET.get('q', '').strip()
    if q:
        products = products.filter(Q(title__icontains=q) | Q(barcode=q) | Q(category__title__icontains=q))
    category = request.GET.get('category', '')
    if category.isdigit():
        products = products.filter(category_id=category)
    threshold = get_low_stock_threshold()
    status = request.GET.get('status', '')
    if status == 'low':
        products = products.filter(active=True, qty__lt=threshold)
    elif status == 'inactive':
        products = products.filter(active=False)
    elif status != 'all':
        products = products.filter(active=True)

    page = Paginator(products.order_by('title'), 50).get_page(request.GET.get('page'))
    return render(request, 'product/list.html', {
        'page_obj': page,
        'categories': Category.objects.all(),
        'q': q,
        'category': category,
        'status': status,
        'threshold': threshold,
        'low_count': Product.objects.filter(active=True, qty__lt=threshold).count(),
    })


@manager_required
def product_create(request):
    form = ProductForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            product = form.save()
            initial = form.cleaned_data.get('initial_qty') or 0
            if initial > 0:
                adjust_stock(product.pk, 'add', initial, user=request.user, description='Stock initial')
        messages.success(request, f'Produit « {product.title} » ajouté.')
        if 'again' in request.POST:
            return redirect('product:add_product')
        return redirect('product:product_list')
    return render(request, 'product/form.html', {'form': form, 'title': 'Nouveau produit'})


@manager_required
def product_edit(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Produit « {product.title} » modifié.')
        return redirect('product:product_list')
    return render(request, 'product/form.html', {'form': form, 'product': product,
                                                 'title': f'Modifier « {product.title} »'})


@manager_required
def product_stock(request, pk):
    product = get_object_or_404(Product, pk=pk)
    form = StockForm(request.POST or None, initial={'unit_cost': product.prix_achat or None})
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            if d['action'] == 'restock':
                restock(product.pk, d['quantity'], d['unit_cost'], user=request.user,
                        fournisseur=d['fournisseur'], description=d['description'])
            else:
                adjust_stock(product.pk, d['action'], d['quantity'], user=request.user,
                             description=d['description'])
        except StockError as exc:
            messages.error(request, str(exc))
        else:
            product.refresh_from_db()
            messages.success(request, f'Stock de « {product.title} » : {product.qty}.')
            return redirect('product:product_list')
    movements = MouvementStock.objects.filter(produit=product).select_related('created_by')[:15]
    return render(request, 'product/stock.html', {'form': form, 'product': product, 'movements': movements})


@require_POST
@manager_required
def product_toggle(request, pk):
    product = get_object_or_404(Product, pk=pk)
    product.active = not product.active
    product.save(update_fields=['active', 'updated_at'])
    messages.success(request, f'« {product.title} » {"remis en vente" if product.active else "retiré de la vente"}.')
    return redirect(request.POST.get('next') or 'product:product_list')


@manager_required
def product_delete(request, pk):
    product = get_object_or_404(Product, pk=pk)
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
    form = CategoryForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        category = form.save()
        messages.success(request, f'Catégorie « {category.title} » créée.')
        return redirect('product:category_management')
    from django.db.models import Count
    categories = Category.objects.annotate(n=Count('product'))
    return render(request, 'product/categories.html', {'form': form, 'categories': categories})


@require_POST
@manager_required
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    category.delete()
    messages.success(request, f'Catégorie « {category.title} » supprimée (ses produits restent, sans catégorie).')
    return redirect('product:category_management')


# ---------------------------------------------------------------- Approvisionnement (réception)

@manager_required
def restock_page(request):
    return render(request, 'product/restock.html', {'categories': Category.objects.all()})


@require_GET
@api_manager_required
def api_stock_catalog(request):
    """Catalogue de la réception : tous les produits (même retirés de la vente), avec prix d'achat."""
    rows = Product.objects.order_by('title').values_list(
        'id', 'title', 'barcode', 'value', 'qty', 'category_id', 'prix_achat', 'active', 'discount_value')
    return json_etag_response(request, {
        'currency': AppSetting.get_currency_label(),
        'products': [[pid, title, barcode or '', to_cents(value), qty, cat or 0, to_cents(cost),
                      1 if active else 0, to_cents(promo)]
                     for pid, title, barcode, value, qty, cat, cost, active, promo in rows],
        'categories': list(Category.objects.order_by('title').values_list('id', 'title')),
    })


@require_POST
@api_manager_required
def api_receive(request):
    try:
        payload = json.loads(request.body or b'{}')
        key = uuid.UUID(str(payload['key'])) if payload.get('key') else None
    except (ValueError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)
    try:
        result = receive(payload.get('lines'), user=request.user, key=key,
                         fournisseur=str(payload.get('fournisseur') or ''),
                         reference=str(payload.get('reference') or ''))
    except StockError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if result is None:
        return JsonResponse({'ok': True, 'replayed': True})
    return JsonResponse({'ok': True, 'replayed': False, 'lines': result['lines'], 'units': result['units'],
                         'created': result['created'], 'total': to_cents(result['total'])})
