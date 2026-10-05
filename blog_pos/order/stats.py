"""Chiffres du tableau de bord — tout en Decimal, agrégé en SQL."""
import calendar
import datetime
from decimal import Decimal

from django.db.models import Count, F, Sum

from aprovision.models import Depense
from .models import Order, OrderItem, Payment

ZERO = Decimal('0.00')
APPRO = 'Approvisionnement'


def sales_summary(orders):
    agg = orders.aggregate(n=Count('id'), total=Sum('final_value'), paid=Sum('amount_paid'))
    total = agg['total'] or ZERO
    paid = agg['paid'] or ZERO
    return {'count': agg['n'], 'total': total, 'paid': paid, 'remaining': total - paid}


def daily_series(orders, start, end):
    """Total des ventes par jour (jours sans vente inclus), pour les graphiques SVG."""
    rows = dict(orders.filter(date__gte=start, date__lte=end)
                .values('date').annotate(t=Sum('final_value')).values_list('date', 't'))
    days = []
    day = start
    while day <= end:
        days.append({'date': day, 'total': rows.get(day) or ZERO})
        day += datetime.timedelta(days=1)
    peak = max((d['total'] for d in days), default=ZERO)
    for d in days:
        d['pct'] = int(d['total'] * 100 / peak) if peak > 0 else 0
    return days


def previous_period(start, end):
    """Période de comparaison.

    Un mois (entier ou commencé) se compare aux mêmes jours du mois précédent
    (1er–5 octobre → 1er–5 septembre ; octobre entier → septembre entier).
    Sinon, la même durée juste avant (aujourd'hui → hier, 7 jours → les 7 d'avant).
    """
    if start.day == 1 and (start.year, start.month) == (end.year, end.month):
        prev_start = (start - datetime.timedelta(days=1)).replace(day=1)
        prev_last = calendar.monthrange(prev_start.year, prev_start.month)[1]
        full_month = end.day == calendar.monthrange(end.year, end.month)[1]
        return prev_start, prev_start.replace(day=prev_last if full_month else min(end.day, prev_last))
    prev_end = start - datetime.timedelta(days=1)
    return prev_end - (end - start), prev_end


def period_figures(start, end):
    """CA, marge, dépenses et bénéfice d'une période (dates incluses)."""
    orders = Order.objects.filter(date__gte=start, date__lte=end)
    sales = sales_summary(orders)
    items = OrderItem.objects.filter(order__in=orders)
    agg = items.aggregate(units=Sum('qty'), cost=Sum(F('qty') * F('cost_price')))
    cogs = agg['cost'] or ZERO
    expenses = Depense.objects.filter(date_depense__gte=start, date_depense__lte=end)
    other = expenses.exclude(type_depense__nom=APPRO)
    other_total = other.aggregate(s=Sum('montant'))['s'] or ZERO
    margin = sales['total'] - cogs
    return {
        'orders': orders, 'items': items, 'expenses': expenses, 'other': other,
        'sales': sales, 'units': agg['units'] or 0, 'cogs': cogs, 'margin': margin,
        'other_total': other_total, 'net': margin - other_total,
    }


def user_day(user, day):
    """La journée d'un vendeur : ventes qu'il a faites et argent qu'il a encaissé (crédits remboursés compris)."""
    return {
        'count': Order.objects.filter(created_by=user, date=day).count(),
        'collected': Payment.objects.filter(created_by=user, date=day).aggregate(s=Sum('amount'))['s'] or ZERO,
    }


def change(current, previous, higher_is_better=True):
    """Variation en % par rapport à la période précédente (None s'il n'y a rien à comparer)."""
    if not previous:
        return None
    pct = int(round((current - previous) * 100 / abs(previous)))
    return {'pct': pct, 'abs': abs(pct), 'good': pct == 0 or (pct > 0) == higher_is_better}
