from django.shortcuts import redirect

EXEMPT_PREFIXES = ('/users/setup/', '/users/login/', '/users/forgot-password/', '/admin/', '/static/', '/media/',
                   '/healthz')


class SetupMiddleware:
    """Tant qu'aucun compte n'existe, toute page renvoie vers la configuration initiale."""

    setup_done = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not SetupMiddleware.setup_done and not request.path.startswith(EXEMPT_PREFIXES):
            from .models import User
            if User.objects.exists():
                SetupMiddleware.setup_done = True
            else:
                return redirect('users:setup')
        return self.get_response(request)
