import datetime
import hashlib
import json
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Max, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from aprovision.models import Depense
from core.decorators import api_login_required, manager_required
from core.utils import format_money, parse_iso_date, to_cents
from product.models import Category, Product, get_low_stock_threshold
from users.models import AppSetting
from . import services
from .models import Order, OrderItem, PaymentMethod

ZERO = services.ZERO


# ---------------------------------------------------------------- Caisse

@login_required
def pos_view(request):
    return render(request, 'order/pos.html', {
        'methods': PaymentMethod.choices,
    })


@require_GET
@api_login_required
def api_catalog(request):
    """Catalogue compact de la caisse, mis en cache par le navigateur (ETag → 304)."""
    products = Product.objects.filter(active=True)
    state = products.aggregate(n=Count('id'), last=Max('updated_at'))
    cat_state = Category.objects.aggregate(n=Count('id'), last=Max('updated_at'))
    settings_obj = AppSetting.get_solo()
    fingerprint = f"{state}|{cat_state}|{settings_obj.currency_label}|{settings_obj.updated_at}"
    etag = '"' + hashlib.md5(fingerprint.encode()).hexdigest() + '"'
    # GZipMiddleware rend l'ETag « faible » (W/"…") : on compare sans ce préfixe.
    if request.headers.get('If-None-Match', '').replace('W/', '') == etag:
        response = HttpResponse(status=304)
        response['ETag'] = etag
        return response

    rows = products.order_by('title').values_list('id', 'title', 'barcode', 'final_value', 'qty', 'category_id')
    data = {
        'currency': settings_obj.currency_label,
        'products': [[pid, title, barcode or '', to_cents(price), qty, cat or 0]
                     for pid, title, barcode, price, qty, cat in rows],
        'categories': list(Category.objects.order_by('title').values_list('id', 'title')),
    }
    response = JsonResponse(data, json_dumps_params={'separators': (',', ':'), 'ensure_ascii': False})
    response['ETag'] = etag
    response['Cache-Control'] = 'private, no-cache'
    return response


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
    return JsonResponse({
        'ok': True,
        'replayed': result.replayed,
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

def sales_summary(orders):
    agg = orders.aggregate(n=Count('id'), total=Sum('final_value'), paid=Sum('amount_paid'))
    total = agg['total'] or ZERO
    paid = agg['paid'] or ZERO
    return {'count': agg['n'], 'total': total, 'paid': paid, 'remaining': total - paid}


def daily_series(orders, start, end):
    """Total des ventes par jour (jours sans vente inclus), pour les graphiques SVG."""
    rows = dict(orders.values('date').annotate(t=Sum('final_value')).values_list('date', 't'))
    days = []
    day = start
    while day <= end:
        days.append({'date': day, 'total': rows.get(day) or ZERO})
        day += datetime.timedelta(days=1)
    peak = max((d['total'] for d in days), default=ZERO)
    for d in days:
        d['pct'] = int(d['total'] * 100 / peak) if peak > 0 else 0
    return days


@manager_required
def dashboard_view(request):
    today = timezone.localdate()
    week_start = today - datetime.timedelta(days=6)
    month_start = today.replace(day=1)
    orders = Order.objects.all()

    today_stats = sales_summary(orders.filter(date=today))
    yesterday_stats = sales_summary(orders.filter(date=today - datetime.timedelta(days=1)))
    month_orders = orders.filter(date__gte=month_start, date__lte=today)
    month_stats = sales_summary(month_orders)

    month_cost = (OrderItem.objects.filter(order__in=month_orders)
                  .aggregate(c=Sum(F('qty') * F('cost_price')))['c'] or ZERO)
    month_expenses = (Depense.objects.filter(date_depense__gte=month_start, date_depense__lte=today)
                      .exclude(type_depense__nom='Approvisionnement')
                      .aggregate(s=Sum('montant'))['s'] or ZERO)

    unpaid = orders.filter(is_paid=False).aggregate(
        s=Sum(F('final_value') - F('amount_paid')), n=Count('id'))
    threshold = get_low_stock_threshold()

    return render(request, 'order/dashboard.html', {
        'today': today,
        'today_stats': today_stats,
        'yesterday_stats': yesterday_stats,
        'month_stats': month_stats,
        'month_margin': month_stats['total'] - month_cost,
        'month_expenses': month_expenses,
        'month_net': month_stats['total'] - month_cost - month_expenses,
        'unpaid_total': unpaid['s'] or ZERO,
        'unpaid_count': unpaid['n'],
        'week': daily_series(orders, week_start, today),
        'top_products': (OrderItem.objects.filter(order__in=month_orders)
                         .values('product__title').annotate(qty=Sum('qty'), total=Sum('total_price'))
                         .order_by('-qty')[:5]),
        'low_stock': Product.objects.filter(active=True, qty__lt=threshold).order_by('qty', 'title')[:8],
        'threshold': threshold,
        'recent_orders': orders.select_related('client')[:6],
    })
