"""
Envoi du lien de réinitialisation de mot de passe.

L'envoi passe par le backend email des settings : SMTP de Resend en production
(EMAIL_HOST=smtp.resend.com, voir DEPLOY.md), console en développement. Une
défaillance réseau ne lève pas d'exception ici : la fonction renvoie False et
l'appelant prévient l'utilisateur.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.utils.html import escape

logger = logging.getLogger('welto.email')


def send_reset_link_email(user, link):
    """Envoie le lien de réinitialisation. Retourne True si l'envoi a réussi."""
    company = _company_name(user)
    name = user.get_full_name() or user.username
    hours = settings.PASSWORD_RESET_TIMEOUT // 3600
    subject = f'{company} — Choisir un nouveau mot de passe'
    text = (
        f'Bonjour {name},\n\n'
        f'Vous avez demandé un nouveau mot de passe pour votre compte {company} (identifiant : {user.username}).\n\n'
        f'Ouvrez ce lien pour le choisir :\n{link}\n\n'
        f'Le lien est valable {hours} heure{"s" if hours > 1 else ""} et ne sert qu\'une fois.\n'
        f'Si vous n\'êtes pas à l\'origine de cette demande, ignorez cet email : votre mot de passe reste inchangé.\n\n'
        f'— {company}'
    )
    html = (
        '<div style="font-family:Arial,sans-serif;font-size:15px;color:#0f172a;max-width:480px">'
        f'<p>Bonjour {escape(name)},</p>'
        f'<p>Vous avez demandé un nouveau mot de passe pour votre compte <b>{escape(company)}</b> '
        f'(identifiant : <b>{escape(user.username)}</b>).</p>'
        f'<p style="margin:28px 0"><a href="{escape(link)}" style="background:#0e6dfa;color:#fff;padding:12px 22px;'
        'border-radius:10px;text-decoration:none;font-weight:bold">Choisir mon nouveau mot de passe</a></p>'
        f'<p style="color:#64748b;font-size:13px">Le lien est valable {hours} heure{"s" if hours > 1 else ""} et ne sert '
        'qu\'une fois. Si vous n\'êtes pas à l\'origine de cette demande, ignorez cet email.</p>'
        f'<p style="color:#64748b;font-size:13px">— {escape(company)}</p></div>'
    )
    try:
        send_mail(subject, text, None, [user.email], html_message=html, fail_silently=False)
        logger.info('Lien de réinitialisation envoyé à %s', user.email)
        return True
    except Exception as exc:
        logger.warning('Échec envoi du lien de réinitialisation à %s : %s', user.email, exc)
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
