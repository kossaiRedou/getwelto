import datetime
from decimal import Decimal

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, F, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.decorators import manager_required
from core.utils import parse_iso_date
from order.models import Order, OrderItem, Payment, PaymentMethod
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
    """Ancienne page « Rapports » : fusionnée dans le tableau de bord."""
    url = reverse('dashboard')
    if request.GET:
        url += '?' + request.GET.urlencode()
    return redirect(url)


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
