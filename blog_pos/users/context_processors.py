from users.models import AppSetting


def app_settings(request):
    """Injecte currency et company_name dans tous les templates."""
    setting = AppSetting.get_solo()
    return {
        'currency': setting.currency_label or 'GMD',
        'company_name': setting.company_name or '',
    }