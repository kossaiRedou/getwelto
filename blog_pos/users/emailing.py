"""
Envoi des emails de récupération de mot de passe.

L'envoi passe par le backend email configuré dans les settings (SMTP en
production, console en développement). Une défaillance réseau ne lève pas
d'exception ici : la fonction renvoie False et l'appelant informe l'utilisateur
qu'une connexion Internet est nécessaire.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger('welto.email')


def send_reset_code_email(user, code):
    """Envoie le code de réinitialisation. Retourne True si l'envoi a réussi."""
    company = _company_name(user)
    subject = f'{company} — Code de réinitialisation de mot de passe'
    validity = _validity_minutes()
    message = (
        f'Bonjour {user.get_full_name() or user.username},\n\n'
        f'Vous avez demandé la réinitialisation de votre mot de passe {company}.\n\n'
        f'Votre code de réinitialisation est : {code}\n\n'
        f'Ce code est valable {validity} minutes. Saisissez-le dans l\'application '
        f'pour définir un nouveau mot de passe.\n\n'
        f'Si vous n\'êtes pas à l\'origine de cette demande, ignorez cet email : '
        f'votre mot de passe reste inchangé.\n\n'
        f'— {company}'
    )
    from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or 'no-reply@welto.app'

    try:
        send_mail(subject, message, from_email, [user.email], fail_silently=False)
        logger.info('Code de réinitialisation envoyé à %s', user.email)
        return True
    except Exception as exc:
        logger.warning('Échec envoi email de réinitialisation à %s : %s', user.email, exc)
        return False


def _company_name(user):
    try:
        from .models import AppSetting
        if user.account_id:
            setting = AppSetting.for_account(user.account)
            return setting.company_name or user.account.name
    except Exception:
        pass
    return 'WELTO'


def _validity_minutes():
    try:
        from .models import PasswordResetCode
        return PasswordResetCode.VALIDITY_MINUTES
    except Exception:
        return 15
