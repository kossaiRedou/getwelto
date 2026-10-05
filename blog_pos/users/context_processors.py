from django.conf import settings


def app_settings(request):
    """Devise, nom de l'entreprise et boutique courante dans tous les templates."""
    scope = getattr(request, 'scope', None)
    data = {'saas_contact': settings.SAAS_CONTACT, 'scope': scope}
    if scope is None:
        return data
    setting = scope.settings()
    data.update({
        'currency': scope.account.currency,
        'company_name': setting.company_name or scope.account.name,
        'account': scope.account,
    })
    return data
