from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.decorators import is_manager, manager_required
from core.throttle import is_locked
from .emailing import send_reset_code_email
from .forms import (AppSettingForm, CustomUserChangeForm, CustomUserCreationForm, ForgotCodeForm,
                    ForgotRequestForm, ManagerResetPasswordForm, PasswordChangeForm)
from .models import PasswordResetCode, User


def login_view(request):
    if request.user.is_authenticated:
        return redirect('pos')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        if is_locked(username, request):
            messages.error(request, 'Trop de tentatives de connexion. Réessayez dans 15 minutes '
                                    'ou demandez au gérant de réinitialiser votre mot de passe.')
            return render(request, 'users/login.html', {'username': username}, status=429)
        user = authenticate(request, username=username, password=password) if username and password else None
        if user is not None and user.account_id and not user.account.is_open:
            # Bon mot de passe, mais compte en attente, suspendu ou arrivé à sa date de fin.
            messages.error(request, user.account.blocked_message())
            return render(request, 'users/login.html', {'username': username})
        if user is not None:
            login(request, user)
            if user.account_id is None:
                return redirect('admin:index')   # propriétaire du SaaS
            next_url = request.GET.get('next', '')
            if next_url and url_has_allowed_host_and_scheme(next_url, {request.get_host()}, request.is_secure()) \
                    and not next_url.startswith('/admin/'):
                return redirect(next_url)
            return redirect('pos')
        messages.error(request, 'Identifiant ou mot de passe incorrect.')
    return render(request, 'users/login.html', {'username': request.POST.get('username', '')})


@require_POST
def logout_view(request):
    logout(request)
    return redirect('users:login')


@manager_required
def app_settings_view(request):
    settings_obj = request.scope.settings()
    form = AppSettingForm(request.POST or None, request.FILES or None, instance=settings_obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Paramètres enregistrés.')
        return redirect('users:app_settings')
    return render(request, 'users/app_settings.html', {'form': form})


@manager_required
def user_list_view(request):
    users = request.scope.users().select_related('shop').order_by('role', '-is_active', 'first_name')
    q = request.GET.get('q', '').strip()
    if q:
        users = users.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) |
                             Q(username__icontains=q) | Q(phone__icontains=q))
    page = Paginator(users, 30).get_page(request.GET.get('page'))
    return render(request, 'users/user_list.html', {'page_obj': page, 'q': q})


@manager_required
def user_create_view(request):
    form = CustomUserCreationForm(request.POST or None, request_user=request.user, scope=request.scope)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        messages.success(request, f'Utilisateur « {user.get_full_name() or user.username} » créé.')
        return redirect('users:user_list')
    return render(request, 'users/user_form.html', {'form': form, 'title': 'Nouvel utilisateur'})


@manager_required
def user_update_view(request, pk):
    target = get_object_or_404(request.scope.users(), pk=pk)
    form = CustomUserChangeForm(request.POST or None, instance=target, request_user=request.user,
                                scope=request.scope)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, f'Utilisateur « {target.get_full_name() or target.username} » modifié.')
        return redirect('users:user_list')
    return render(request, 'users/user_form.html', {'form': form, 'target': target,
                                                    'title': f'Modifier {target.get_full_name() or target.username}'})


@manager_required
def user_delete_view(request, pk):
    target = get_object_or_404(request.scope.users(), pk=pk)
    if target == request.user or target.role == 'manager':
        messages.error(request, 'Vous ne pouvez pas supprimer votre propre compte.')
        return redirect('users:user_list')
    if request.method == 'POST':
        target.delete()
        messages.success(request, 'Utilisateur supprimé.')
        return redirect('users:user_list')
    return render(request, 'core/confirm.html', {
        'title': "Supprimer l'utilisateur",
        'message': f'Supprimer le compte « {target.get_full_name() or target.username} » ? '
                   'Ses ventes restent enregistrées. Vous pouvez aussi simplement le désactiver.',
        'cancel_url': 'users:user_list',
    })


@login_required
def change_password_view(request, pk):
    """Un manager réinitialise le mot de passe d'un autre compte sans connaître l'ancien."""
    target = get_object_or_404(request.scope.users(), pk=pk)
    if target == request.user:
        return redirect('users:my_password_change')
    if not is_manager(request.user):
        messages.error(request, 'Accès refusé.')
        return redirect('pos')
    form = ManagerResetPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        target.set_password(form.cleaned_data['new_password1'])
        target.save()
        messages.success(request, f'Mot de passe de {target.get_full_name() or target.username} réinitialisé.')
        return redirect('users:user_list')
    return render(request, 'users/change_password.html', {
        'form': form, 'title': f'Nouveau mot de passe pour {target.get_full_name() or target.username}'})


@login_required
def my_password_change_view(request):
    form = PasswordChangeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        if not request.user.check_password(form.cleaned_data['current_password']):
            form.add_error('current_password', 'Mot de passe actuel incorrect.')
        else:
            request.user.set_password(form.cleaned_data['new_password1'])
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'Mot de passe modifié.')
            return redirect('pos')
    return render(request, 'users/change_password.html', {'form': form, 'title': 'Changer mon mot de passe'})


# --- Mot de passe oublié (code envoyé par email) ---

FORGOT_SESSION_KEY = 'forgot_pw_user_id'


def forgot_password_view(request):
    if request.user.is_authenticated:
        return redirect('pos')
    form = ForgotRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        identifier = form.cleaned_data['identifier'].strip()
        user = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier),
                                   is_active=True).first()
        # Message identique que le compte existe ou non (ne révèle pas les comptes existants).
        neutral = 'Si un compte correspond, un code vient d\'être envoyé à son adresse email.'
        if user and user.email:
            _, raw_code = PasswordResetCode.issue_for(user)
            if not send_reset_code_email(user, raw_code):
                messages.error(request, "L'envoi de l'email a échoué. Réessayez dans un instant.")
                return redirect('users:forgot_password')
            request.session[FORGOT_SESSION_KEY] = user.id
            messages.success(request, neutral)
            return redirect('users:forgot_password_code')
        messages.success(request, neutral)
        return redirect('users:forgot_password')
    return render(request, 'users/forgot_password.html', {'form': form})


def forgot_password_code_view(request):
    if request.user.is_authenticated:
        return redirect('pos')
    user = User.objects.filter(id=request.session.get(FORGOT_SESSION_KEY), is_active=True).first()
    if not user:
        request.session.pop(FORGOT_SESSION_KEY, None)
        return redirect('users:forgot_password')

    form = ForgotCodeForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        code_obj = PasswordResetCode.objects.filter(user=user, used=False).order_by('-created_at').first()
        if not code_obj or not code_obj.is_valid():
            messages.error(request, 'Code expiré ou invalide. Recommencez la demande.')
            request.session.pop(FORGOT_SESSION_KEY, None)
            return redirect('users:forgot_password')
        code_obj.register_attempt()
        if code_obj.check_code(form.cleaned_data['code']):
            user.set_password(form.cleaned_data['new_password1'])
            user.save()
            code_obj.used = True
            code_obj.save(update_fields=['used'])
            request.session.pop(FORGOT_SESSION_KEY, None)
            messages.success(request, 'Mot de passe réinitialisé. Vous pouvez vous connecter.')
            return redirect('users:login')
        remaining = PasswordResetCode.MAX_ATTEMPTS - code_obj.attempts
        if remaining <= 0:
            code_obj.used = True
            code_obj.save(update_fields=['used'])
            request.session.pop(FORGOT_SESSION_KEY, None)
            messages.error(request, 'Trop de tentatives. Recommencez la demande.')
            return redirect('users:forgot_password')
        messages.error(request, f'Code incorrect. Il vous reste {remaining} tentative(s).')
    return render(request, 'users/forgot_password_code.html',
                  {'form': form, 'masked_email': _mask_email(user.email)})


def _mask_email(email):
    if not email or '@' not in email:
        return ''
    local, domain = email.split('@', 1)
    return f'{local[:1]}***@{domain}'
