import datetime
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import manager_required
from core.utils import parse_iso_date
from order.models import Order, OrderItem, Payment, PaymentMethod
from order.views import daily_series, sales_summary
from product.models import Product
from .forms import DepenseForm
from .models import Depense, MouvementStock, TypeDepense, TypeMouvement

ZERO = Decimal('0.00')
APPRO = 'Approvisionnement'


def _period(request, default_start):
    today = timezone.localdate()
    start = parse_iso_date(request.GET.get('start'), default_start)
    end = parse_iso_date(request.GET.get('end'), today)
    if start > end:
        start, end = end, start
    return start, end


@manager_required
def reports_view(request):
    today = timezone.localdate()
    start, end = _period(request, today.replace(day=1))

    orders = Order.objects.filter(date__gte=start, date__lte=end)
    sales = sales_summary(orders)
    items = OrderItem.objects.filter(order__in=orders)
    item_agg = items.aggregate(units=Sum('qty'), cost=Sum(F('qty') * F('cost_price')))
    cogs = item_agg['cost'] or ZERO

    payments = Payment.objects.filter(date__gte=start, date__lte=end)
    labels = dict(PaymentMethod.choices)
    by_method = [{'label': labels.get(row['method'], row['method']), 'total': row['s']}
                 for row in payments.values('method').annotate(s=Sum('amount')).order_by('-s')]

    expenses = Depense.objects.filter(date_depense__gte=start, date_depense__lte=end)
    purchases = expenses.filter(type_depense__nom=APPRO).aggregate(s=Sum('montant'))['s'] or ZERO
    other = expenses.exclude(type_depense__nom=APPRO)
    other_total = other.aggregate(s=Sum('montant'))['s'] or ZERO
    margin = sales['total'] - cogs

    days = (end - start).days + 1
    return render(request, 'aprovision/reports.html', {
        'start': start,
        'end': end,
        'sales': sales,
        'qty_sold': item_agg['units'] or 0,
        'avg_basket': (sales['total'] / sales['count']) if sales['count'] else ZERO,
        'cogs': cogs,
        'margin': margin,
        'missing_cost': items.filter(cost_price=0).values('product').distinct().count(),
        'collected': payments.aggregate(s=Sum('amount'))['s'] or ZERO,
        'by_method': by_method,
        'purchases': purchases,
        'other_total': other_total,
        'other_by_type': other.values('type_depense__nom').annotate(s=Sum('montant')).order_by('-s'),
        'net': margin - other_total,
        'series': daily_series(orders, start, end) if days <= 62 else None,
        'top_products': items.values('product__title').annotate(qty=Sum('qty'), total=Sum('total_price'))
                             .order_by('-total')[:10],
        'by_category': items.values('product__category__title').annotate(qty=Sum('qty'), total=Sum('total_price'))
                            .order_by('-total'),
        'presets': [
            ("Aujourd'hui", today, today),
            ('7 jours', today - datetime.timedelta(days=6), today),
            ('Ce mois', today.replace(day=1), today),
            ('30 jours', today - datetime.timedelta(days=29), today),
        ],
    })


@manager_required
def depense_list(request):
    today = timezone.localdate()
    start, end = _period(request, today.replace(day=1))
    depenses = (Depense.objects.select_related('type_depense', 'created_by')
                .filter(date_depense__gte=start, date_depense__lte=end))
    type_id = request.GET.get('type', '')
    if type_id.isdigit():
        depenses = depenses.filter(type_depense_id=type_id)
    page = Paginator(depenses, 50).get_page(request.GET.get('page'))
    return render(request, 'aprovision/depense_list.html', {
        'page_obj': page,
        'total': depenses.aggregate(s=Sum('montant'))['s'] or ZERO,
        'by_type': depenses.values('type_depense__nom').annotate(s=Sum('montant'), n=Count('id')).order_by('-s'),
        'types': TypeDepense.objects.filter(actif=True),
        'type_id': type_id,
        'start': start,
        'end': end,
    })


@manager_required
def depense_create(request):
    form = DepenseForm(request.POST or None, initial={'date_depense': timezone.localdate()})
    if request.method == 'POST' and form.is_valid():
        depense = form.save(commit=False)
        depense.created_by = request.user
        depense.save()
        messages.success(request, 'Dépense enregistrée.')
        return redirect('aprovision:depense_list')
    return render(request, 'aprovision/depense_form.html', {'form': form})


@require_POST
@manager_required
def depense_delete(request, pk):
    depense = get_object_or_404(Depense, pk=pk)
    if MouvementStock.objects.filter(reference_depense=depense).exists():
        messages.error(request, "Cette dépense est liée à un approvisionnement : corrigez le stock du produit à la place.")
    else:
        depense.delete()
        messages.success(request, 'Dépense supprimée.')
    return redirect('aprovision:depense_list')


@manager_required
def mouvement_list(request):
    mouvements = MouvementStock.objects.select_related('produit', 'reference_commande', 'created_by')
    kind = request.GET.get('type', '')
    if kind in TypeMouvement.values:
        mouvements = mouvements.filter(type_mouvement=kind)
    product_id = request.GET.get('product', '')
    if product_id.isdigit():
        mouvements = mouvements.filter(produit_id=product_id)
    start = parse_iso_date(request.GET.get('start'))
    end = parse_iso_date(request.GET.get('end'))
    if start:
        mouvements = mouvements.filter(date_mouvement__date__gte=start)
    if end:
        mouvements = mouvements.filter(date_mouvement__date__lte=end)
    page = Paginator(mouvements, 50).get_page(request.GET.get('page'))
    return render(request, 'aprovision/mouvement_list.html', {
        'page_obj': page,
        'types': TypeMouvement.choices,
        'kind': kind,
        'products': Product.objects.order_by('title').values_list('id', 'title'),
        'product_id': product_id,
        'start': start,
        'end': end,
    })
