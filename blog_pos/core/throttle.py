"""
Limitation des tentatives de connexion (application et /admin/).

Après MAX_PER_USER échecs sur un même identifiant, ou MAX_PER_IP depuis une
même adresse, toute connexion est refusée pendant LOCK_SECONDS — même avec le
bon mot de passe. Les compteurs vivent dans le cache partagé (table en base),
donc valent pour tous les processus du serveur.
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver

MAX_PER_USER = 5
MAX_PER_IP = 20
LOCK_SECONDS = 15 * 60


def client_ip(request):
    if request is None:
        return ''
    # Derrière Cloudflare, l'adresse réelle du visiteur est dans CF-Connecting-IP.
    return (request.headers.get('CF-Connecting-IP') or request.META.get('REMOTE_ADDR') or '').strip()


def _keys(username, request):
    keys = []
    if username:
        keys.append((f'login-fail:user:{username.strip().lower()}', MAX_PER_USER))
    ip = client_ip(request)
    if ip:
        keys.append((f'login-fail:ip:{ip}', MAX_PER_IP))
    return keys


def is_locked(username, request):
    return any((cache.get(key) or 0) >= limit for key, limit in _keys(username, request))


class ThrottledModelBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(self._username_field())
        if is_locked(username, request):
            raise PermissionDenied('Trop de tentatives de connexion.')
        return super().authenticate(request, username=username, password=password, **kwargs)

    @staticmethod
    def _username_field():
        from django.contrib.auth import get_user_model
        return get_user_model().USERNAME_FIELD


@receiver(user_login_failed)
def _count_failure(sender, credentials, request=None, **kwargs):
    for key, _ in _keys(credentials.get('username'), request):
        cache.add(key, 0, LOCK_SECONDS)
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, LOCK_SECONDS)


@receiver(user_logged_in)
def _reset_user(sender, request, user, **kwargs):
    cache.delete(f'login-fail:user:{user.get_username().strip().lower()}')
