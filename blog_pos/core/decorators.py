from functools import wraps

from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.http import JsonResponse
from django.shortcuts import redirect


def is_manager(user):
    return user.is_authenticated and (getattr(user, 'role', None) == 'manager' or user.is_superuser)


def manager_required(view_func):
    """Page réservée au manager : connexion requise, sinon retour à la caisse."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not is_manager(request.user):
            messages.error(request, 'Accès réservé au manager.')
            return redirect('pos')
        return view_func(request, *args, **kwargs)
    return wrapper


def api_login_required(view_func):
    """Comme login_required, mais répond 401 en JSON (la caisse affiche « session expirée »)."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'code': 'auth', 'error': 'Session expirée. Reconnectez-vous.'},
                                status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def api_manager_required(view_func):
    """API réservée au manager : 401 si non connecté, 403 sinon."""
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'ok': False, 'code': 'auth', 'error': 'Session expirée. Reconnectez-vous.'},
                                status=401)
        if not is_manager(request.user):
            return JsonResponse({'ok': False, 'code': 'forbidden', 'error': 'Accès réservé au manager.'},
                                status=403)
        return view_func(request, *args, **kwargs)
    return wrapper
