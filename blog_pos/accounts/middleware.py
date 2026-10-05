from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect

from .scope import Scope, activate, deactivate

SESSION_SHOP = 'welto_shop'
ALL_SHOPS = 'all'
# Pages accessibles au propriétaire du SaaS (superutilisateur sans compte client).
OWNER_PATHS = ('/admin/', '/static/', '/media/', '/healthz', '/users/logout/')


class TenantMiddleware:
    """Rattache chaque requête à un compte et à une boutique (request.scope).

    Un compte désactivé ou arrivé à sa date de fin est déconnecté aussitôt :
    la vérification a lieu à chaque page, pas seulement à la connexion.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.scope = None
        token = None
        user = request.user
        if user.is_authenticated:
            account = user.account
            if account is None:
                # Propriétaire du SaaS : il travaille dans l'admin Django.
                if user.is_superuser and not request.path.startswith(OWNER_PATHS):
                    return redirect('admin:index')
            else:
                if not account.is_open:
                    message = account.blocked_message()
                    logout(request)
                    messages.error(request, message)
                    return redirect('users:login')
                scope = self._scope(request, user, account)
                if scope is None:
                    logout(request)
                    messages.error(request, "Aucune boutique n'est attribuée à votre compte. Contactez votre gérant.")
                    return redirect('users:login')
                request.scope = scope
                token = activate(account)
        try:
            return self.get_response(request)
        finally:
            if token is not None:
                deactivate(token)

    @staticmethod
    def _scope(request, user, account):
        shops = list(account.shops.filter(is_active=True))
        if user.role == 'manager':
            if len(shops) == 1:
                shop = shops[0]
            else:
                wanted = request.session.get(SESSION_SHOP, ALL_SHOPS)
                shop = next((s for s in shops if str(s.pk) == str(wanted)), None)
            return Scope(user, account, shop, shops)
        shop = next((s for s in shops if s.pk == user.shop_id), None)
        if shop is None:
            return None
        return Scope(user, account, shop, [shop])
