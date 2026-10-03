import json
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from core.decorators import api_login_required, manager_required
from core.utils import parse_iso_date, to_cents
from order.models import Order, OrderItem
from .forms import ClientForm, clean_name_value, clean_phone_value
from .models import Client

ZERO = Decimal('0.00')


def _client_json(client, debt=None):
    data = {'id': client.pk, 'name': client.name, 'phone': client.phone}
    if debt is not None:
        data['debt'] = to_cents(debt)
    return data


@require_GET
@api_login_required
def api_search(request):
    clients = Client.search(request.GET.get('q', ''), limit=8)
    debts = dict(Order.objects.filter(client__in=clients, is_paid=False).values('client')
                 .annotate(d=Sum(F('final_value') - F('amount_paid'))).values_list('client', 'd'))
    return JsonResponse({'clients': [_client_json(c, debts.get(c.pk, ZERO)) for c in clients]})


@require_POST
@api_login_required
def api_create(request):
    try:
        data = json.loads(request.body or b'{}')
        name = clean_name_value(data.get('name'))
        phone = clean_phone_value(data.get('phone'))
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Requête invalide.'}, status=400)
    except forms.ValidationError as exc:
        return JsonResponse({'ok': False, 'error': ' '.join(exc.messages)}, status=400)
    client = Client.objects.create(name=name, phone=phone)
    return JsonResponse({'ok': True, 'client': _client_json(client, ZERO)})


@login_required
def client_list(request):
    clients = Client.objects.annotate(
        n_orders=Count('orders'),
        debt=Coalesce(Sum(F('orders__final_value') - F('orders__amount_paid'),
                          filter=Q(orders__is_paid=False)), ZERO),
    )
    q = request.GET.get('q', '').strip()
    if q:
        clients = clients.filter(Q(name__icontains=q) | Q(phone__icontains=q))
    status = request.GET.get('status', '')
    if status == 'debt':
        clients = clients.filter(debt__gt=0)
    elif status == 'inactive':
        clients = clients.filter(is_active=False)
    page = Paginator(clients.order_by('name'), 30).get_page(request.GET.get('page'))
    total_debt = (Order.objects.filter(is_paid=False, client__isnull=False)
                  .aggregate(s=Sum(F('final_value') - F('amount_paid')))['s'] or ZERO)
    return render(request, 'client/client_list.html', {
        'page_obj': page, 'q': q, 'status': status, 'total_debt': total_debt,
    })


@login_required
def client_create(request):
    form = ClientForm(request.POST or None, initial={'is_active': True})
    if request.method == 'POST' and form.is_valid():
        client = form.save()
        messages.success(request, f'Client « {client.name} » créé.')
        return redirect('client:client_detail', pk=client.pk)
    return render(request, 'client/client_form.html', {'form': form, 'title': 'Nouveau client'})


@login_required
def client_edit(request, pk):
    client = get_object_or_404(Client, pk=pk)
    form = ClientForm(request.POST or None, instance=client)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Client « {client.name} » modifié.')
        return redirect('client:client_detail', pk=client.pk)
    return render(request, 'client/client_form.html', {'form': form, 'client': client,
                                                       'title': f'Modifier {client.name}'})


@manager_required
def client_delete(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if client.orders.exists():
        messages.error(request, f'« {client.name} » a des ventes enregistrées : désactivez-le plutôt.')
        return redirect('client:client_detail', pk=pk)
    if request.method == 'POST':
        client.delete()
        messages.success(request, f'Client « {client.name} » supprimé.')
        return redirect('client:client_list')
    return render(request, 'core/confirm.html', {
        'title': 'Supprimer le client',
        'message': f'Supprimer définitivement « {client.name} » ?',
        'cancel_url': 'client:client_list',
    })


@login_required
def client_detail(request, pk):
    client = get_object_or_404(Client, pk=pk)
    orders = client.orders.all()
    start = parse_iso_date(request.GET.get('start'))
    end = parse_iso_date(request.GET.get('end'))
    if start:
        orders = orders.filter(date__gte=start)
    if end:
        orders = orders.filter(date__lte=end)
    agg = orders.aggregate(n=Count('id'), total=Sum('final_value'), paid=Sum('amount_paid'))
    unpaid = client.orders.filter(is_paid=False).order_by('timestamp')
    return render(request, 'client/client_detail.html', {
        'client': client,
        'orders': orders.order_by('-timestamp')[:50],
        'unpaid_orders': unpaid,
        'debt': client.total_unpaid_amount(),
        'n_orders': agg['n'],
        'total_spent': agg['total'] or ZERO,
        'total_paid': agg['paid'] or ZERO,
        'qty_bought': OrderItem.objects.filter(order__in=orders).aggregate(s=Sum('qty'))['s'] or 0,
        'start': start,
        'end': end,
    })
