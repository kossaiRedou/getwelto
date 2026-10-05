import logging

from django.contrib import messages
from django.core.cache import cache
from django.core.mail import mail_admins
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.decorators import manager_required
from core.throttle import client_ip
from .forms import ShopForm, SignupForm
from .middleware import ALL_SHOPS, SESSION_SHOP

logger = logging.getLogger('welto.accounts')
SIGNUPS_PER_IP_PER_DAY = 5


def signup_view(request):
    """Inscription publique. Le compte attend l'activation par le propriétaire du SaaS (admin Django)."""
    if request.user.is_authenticated:
        return redirect('pos')
    form = SignupForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if form.is_bot:
            return redirect('accounts:signup_done')
        key = f'signup:ip:{client_ip(request)}'
        if (cache.get(key) or 0) >= SIGNUPS_PER_IP_PER_DAY:
            messages.error(request, "Trop d'inscriptions depuis cette connexion aujourd'hui. Réessayez demain.")
            return render(request, 'accounts/signup.html', {'form': form}, status=429)
        account, shop, user = form.save()
        cache.add(key, 0, 24 * 3600)
        cache.incr(key)
        _notify_owner(request, account, user)
        request.session['signup_name'] = user.first_name
        return redirect('accounts:signup_done')
    return render(request, 'accounts/signup.html', {'form': form})


def _notify_owner(request, account, user):
    url = request.build_absolute_uri(reverse('admin:accounts_account_change', args=[account.pk]))
    try:
        mail_admins(f'Nouvelle inscription : {account.name}',
                    f'{account.name} ({account.get_country_display()}, {account.currency})\n'
                    f'Gérant : {user.get_full_name()} — identifiant {user.username}\n'
                    f'Téléphone : {account.phone}\nEmail : {account.email or "—"}\n\n'
                    f'Activer le compte : {url}\n', fail_silently=True)
    except Exception:   # l'inscription ne doit jamais échouer à cause de l'email
        logger.warning("Notification d'inscription non envoyée pour %s", account.name)


def signup_done_view(request):
    return render(request, 'accounts/signup_done.html', {'name': request.session.pop('signup_name', '')})


@require_POST
@manager_required
def switch_shop(request):
    """Le gérant choisit la boutique affichée, ou « Toutes les boutiques »."""
    scope = request.scope
    wanted = request.POST.get('shop', ALL_SHOPS)
    if wanted == ALL_SHOPS or scope.get_shop(wanted):
        request.session[SESSION_SHOP] = wanted
    target = request.POST.get('next') or request.META.get('HTTP_REFERER') or reverse('dashboard')
    if not url_has_allowed_host_and_scheme(target, {request.get_host()}, request.is_secure()):
        target = reverse('dashboard')
    return redirect(target)


@manager_required
def shop_list(request):
    account = request.scope.account
    shops = account.shops.annotate(n_employees=Count('employees', filter=Q(employees__is_active=True)))
    return render(request, 'accounts/shop_list.html', {
        'shops': shops, 'can_add': account.can_add_shop(), 'max_shops': account.max_shops,
    })


@manager_required
def shop_create(request):
    account = request.scope.account
    if not account.can_add_shop():
        messages.error(request, f'Limite atteinte : votre abonnement compte {account.max_shops} '
                                f'boutique{"s" if account.max_shops > 1 else ""}. Contactez votre fournisseur WELTO.')
        return redirect('accounts:shop_list')
    form = ShopForm(request.POST or None, account=account)
    if request.method == 'POST' and form.is_valid():
        shop = form.save()
        messages.success(request, f'Boutique « {shop.name} » créée. Ajoutez maintenant son employé.')
        return redirect('accounts:shop_list')
    return render(request, 'accounts/shop_form.html', {'form': form, 'title': 'Nouvelle boutique'})


@manager_required
def shop_edit(request, pk):
    account = request.scope.account
    shop = get_object_or_404(account.shops, pk=pk)
    form = ShopForm(request.POST or None, instance=shop, account=account)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Boutique « {shop.name} » modifiée.')
        return redirect('accounts:shop_list')
    return render(request, 'accounts/shop_form.html', {'form': form, 'shop': shop, 'title': f'Modifier {shop.name}'})
