import datetime
import json
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.decorators import api_login_required, is_manager, manager_required
from core.utils import format_money, json_etag_response, parse_iso_date, to_cents
from product.models import DEFAULT_CATEGORY_COLOR, Category, Product, get_low_stock_threshold
from users.models import AppSetting
from . import services, stats
from .models import Order, Payment, PaymentMethod

ZERO = services.ZERO


# ---------------------------------------------------------------- Caisse

@login_required
def pos_view(request):
    return render(request, 'order/pos.html', {
        'methods': PaymentMethod.choices,
        'my_day': None if is_manager(request.user) else stats.user_day(request.user, timezone.localdate()),
    })


@require_GET
@api_login_required
def api_catalog(request):
    """Catalogue compact de la caisse, mis en cache par le navigateur (ETag → 304)."""
    rows = (Product.objects.filter(active=True).order_by('title')
            .values_list('id', 'title', 'barcode', 'final_value', 'qty', 'category_id', 'color', 'category__color'))
    return json_etag_response(request, {
        'currency': AppSetting.get_currency_label(),
        'products': [[pid, title, barcode or '', to_cents(price), qty, cat or 0,
                      color or cat_color or DEFAULT_CATEGORY_COLOR]
                     for pid, title, barcode, price, qty, cat, color, cat_color in rows],
        'categories': list(Category.objects.values_list('id', 'title', 'color')),
    })


@require_POST
@api_login_required
def api_checkout(request):
    try:
        payload = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)
    try:
        result = services.checkout(
            lines=payload.get('lines'),
            user=request.user,
            method=payload.get('method'),
            amount=payload.get('amount'),
            discount=payload.get('discount'),
            client_id=payload.get('client_id'),
            expected_total=payload.get('expected_total'),
            sale_key=payload.get('sale_key'),
        )
    except services.SaleError as exc:
        status = 409 if exc.code in ('stock', 'price_changed') else 400
        return JsonResponse({'ok': False, 'error': exc.message, 'code': exc.code, 'data': exc.data},
                            status=status)
    order = result.order
    day = stats.user_day(request.user, timezone.localdate())
    return JsonResponse({
        'ok': True,
        'replayed': result.replayed,
        'my_day': {'count': day['count'], 'collected': to_cents(day['collected'])},
        'order': {
            'id': order.pk,
            'number': order.title,
            'total': to_cents(order.final_value),
            'paid': to_cents(order.amount_paid),
            'remaining': to_cents(order.remaining_amount()),
            'change': to_cents(result.change),
            'client': order.client.name if order.client else '',
            'detail_url': order.get_absolute_url(),
            'ticket_url': f'{order.get_absolute_url()}ticket/',
        },
    })


# ---------------------------------------------------------------- Ventes

def _filtered_orders(request):
    qs = Order.objects.select_related('client', 'created_by')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(client__name__icontains=q) | Q(client__phone__icontains=q))
    start = parse_iso_date(request.GET.get('start'))
    end = parse_iso_date(request.GET.get('end'))
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)
    status = request.GET.get('status')
    if status == 'paid':
        qs = qs.filter(is_paid=True)
    elif status == 'unpaid':
        qs = qs.filter(is_paid=False)
    return qs, start, end


@login_required
def order_list(request):
    qs, start, end = _filtered_orders(request)
    totals = qs.aggregate(n=Count('id'), total=Sum('final_value'), paid=Sum('amount_paid'))
    total = totals['total'] or ZERO
    paid = totals['paid'] or ZERO
    page = Paginator(qs, 30).get_page(request.GET.get('page'))
    return render(request, 'order/list.html', {
        'page_obj': page,
        'count': totals['n'],
        'total': total,
        'paid': paid,
        'remaining': total - paid,
        'q': request.GET.get('q', ''),
        'start': start,
        'end': end,
        'status': request.GET.get('status', ''),
    })


def _order_context(order):
    return {
        'order': order,
        'items': order.order_items.select_related('product'),
        'payments': order.payments.select_related('created_by'),
        'client': order.client,
        'app_settings': AppSetting.get_solo(),
    }


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order.objects.select_related('client', 'created_by'), pk=pk)
    context = _order_context(order)
    context['methods'] = PaymentMethod.choices
    return render(request, 'order/detail.html', context)


@login_required
def order_ticket(request, pk):
    order = get_object_or_404(Order.objects.select_related('client', 'created_by'), pk=pk)
    return render(request, 'order/ticket.html', _order_context(order))


@login_required
def invoice_pdf_view(request, pk):
    from xhtml2pdf import pisa

    order = get_object_or_404(Order.objects.select_related('client'), pk=pk)
    html = render_to_string('invoice/order_invoice_pdf.html', _order_context(order), request=request)
    result = BytesIO()
    pdf = pisa.CreatePDF(src=html, dest=result)
    if pdf.err:
        messages.error(request, 'Erreur lors de la génération de la facture.')
        return redirect(order)
    response = HttpResponse(result.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Facture-{order.title}.pdf"'
    return response


@require_POST
@login_required
def order_add_payment(request, pk):
    order = get_object_or_404(Order, pk=pk)
    try:
        payment = services.add_payment(order.pk, request.POST.get('amount'), request.POST.get('method'),
                                       user=request.user, note=request.POST.get('note', ''))
        messages.success(request, f'Paiement de {format_money(payment.amount)} enregistré.')
    except services.SaleError as exc:
        messages.error(request, exc.message)
    return redirect(order)


@require_POST
@manager_required
def order_delete_payment(request, pk, payment_id):
    order = get_object_or_404(Order, pk=pk)
    try:
        services.delete_payment(order.pk, payment_id)
        messages.success(request, 'Paiement supprimé.')
    except services.SaleError as exc:
        messages.error(request, exc.message)
    return redirect(order)


@require_POST
@manager_required
def order_cancel(request, pk):
    order = get_object_or_404(Order, pk=pk)
    title = services.cancel_sale(order.pk, user=request.user)
    messages.success(request, f'Vente {title} annulée : les articles sont remis en stock.')
    return redirect('order_list')


# ---------------------------------------------------------------- Tableau de bord

def _dashboard_presets(today):
    yesterday = today - datetime.timedelta(days=1)
    month_start = today.replace(day=1)
    last_month_end = month_start - datetime.timedelta(days=1)
    return [
        ("Aujourd'hui", today, today),
        ('Hier', yesterday, yesterday),
        ('7 jours', today - datetime.timedelta(days=6), today),
        ('Ce mois', month_start, today),
        ('Mois dernier', last_month_end.replace(day=1), last_month_end),
        ('30 jours', today - datetime.timedelta(days=29), today),
    ]


@manager_required
def dashboard_view(request):
    """Tableau de bord unique : chiffres de la période choisie (aujourd'hui par défaut),
    comparés à la période précédente, plus la situation du moment (crédits, stock bas)."""
    today = timezone.localdate()
    start = parse_iso_date(request.GET.get('start'), today)
    end = parse_iso_date(request.GET.get('end'), today)
    if start > end:
        start, end = end, start
    days = (end - start).days + 1

    cur = stats.period_figures(start, end)
    prev_start, prev_end = stats.previous_period(start, end)
    prev = stats.period_figures(prev_start, prev_end)
    sales = cur['sales']

    payments = Payment.objects.filter(date__gte=start, date__lte=end)
    collected = payments.aggregate(s=Sum('amount'))['s'] or ZERO
    labels = dict(PaymentMethod.choices)
    by_method = [{'label': labels.get(row['method'], row['method']), 'total': row['s']}
                 for row in payments.values('method').annotate(s=Sum('amount')).order_by('-s')]

    # Un seul jour : on montre la semaine qui se termine ce jour-là, jour choisi en avant.
    if days == 1:
        series = stats.daily_series(Order.objects.all(), end - datetime.timedelta(days=6), end)
        for d in series:
            d['hl'] = d['date'] == end
    elif days <= 62:
        series = stats.daily_series(cur['orders'], start, end)
        for d in series:
            d['hl'] = d['pct'] == 100
    else:
        series = None

    unpaid = Order.objects.filter(is_paid=False).aggregate(
        s=Sum(F('final_value') - F('amount_paid')), n=Count('id'))
    threshold = get_low_stock_threshold()
    low_stock = Product.objects.filter(active=True, qty__lt=threshold)

    return render(request, 'order/dashboard.html', {
        'today': today,
        'start': start,
        'end': end,
        'single_day': days == 1,
        'prev_start': prev_start,
        'prev_end': prev_end,
        'presets': _dashboard_presets(today),
        'sales': sales,
        'prev': prev,
        'avg_basket': (sales['total'] / sales['count']) if sales['count'] else ZERO,
        'qty_sold': cur['units'],
        'cogs': cur['cogs'],
        'margin': cur['margin'],
        'other_total': cur['other_total'],
        'net': cur['net'],
        'delta': {
            'sales': stats.change(sales['total'], prev['sales']['total']),
            'margin': stats.change(cur['margin'], prev['margin']),
            'other': stats.change(cur['other_total'], prev['other_total'], higher_is_better=False),
            'net': stats.change(cur['net'], prev['net']),
        },
        'missing_cost': cur['items'].filter(cost_price=0).values('product').distinct().count(),
        'collected': collected,
        'by_method': by_method,
        'purchases': cur['expenses'].filter(type_depense__nom=stats.APPRO).aggregate(s=Sum('montant'))['s'] or ZERO,
        'other_by_type': cur['other'].values('type_depense__nom').annotate(s=Sum('montant')).order_by('-s'),
        'series': series,
        'top_products': (cur['items'].values('product__title').annotate(qty=Sum('qty'), total=Sum('total_price'))
                         .order_by('-total')[:10]),
        'by_category': (cur['items'].values('product__category__title', 'product__category__color')
                        .annotate(qty=Sum('qty'), total=Sum('total_price')).order_by('-total')),
        'unpaid_total': unpaid['s'] or ZERO,
        'unpaid_count': unpaid['n'],
        'threshold': threshold,
        'low_count': low_stock.count(),
        'low_stock': low_stock.order_by('qty', 'title')[:8],
        'recent_orders': Order.objects.select_related('client')[:6],
    })
