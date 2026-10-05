from functools import wraps

from django.http import JsonResponse
from django.shortcuts import render


def shop_required(view_func):
    """Action propre à une boutique (caisse, réception, stock…).

    En vue « Toutes les boutiques », le gérant choisit d'abord la boutique ;
    une API répond 409 pour que la page le lui demande.
    """
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        scope = getattr(request, 'scope', None)
        if scope is not None and scope.shop is None:
            if request.path.startswith('/api/') or '/api/' in request.path:
                return JsonResponse({'ok': False, 'code': 'shop', 'error': 'Choisissez d\'abord une boutique.'},
                                    status=409)
            return render(request, 'accounts/choose_shop.html', {'next': request.get_full_path()})
        return view_func(request, *args, **kwargs)
    return wrapper
