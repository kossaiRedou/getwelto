from django.contrib import messages
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from core.decorators import is_manager, manager_required
from core.throttle import client_ip, is_locked
from .emailing import send_reset_link_email
from .forms import (AppSettingForm, CustomUserChangeForm, CustomUserCreationForm, ForgotRequestForm,
                    ManagerResetPasswordForm, PasswordChangeForm)
from .models import User


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


# --- Mot de passe oublié : lien envoyé par email (Resend en SMTP) ---

RESET_REQUESTS_PER_IP_PER_HOUR = 5


def forgot_password_view(request):
    """Envoie un lien de réinitialisation à l'email du compte (identifiant ou email saisi)."""
    if request.user.is_authenticated:
        return redirect('pos')
    form = ForgotRequestForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        key = f'reset:ip:{client_ip(request)}'
        if (cache.get(key) or 0) >= RESET_REQUESTS_PER_IP_PER_HOUR:
            messages.error(request, 'Trop de demandes depuis cette connexion. Réessayez dans une heure.')
            return render(request, 'users/forgot_password.html', {'form': form}, status=429)
        cache.add(key, 0, 3600)
        cache.incr(key)
        identifier = form.cleaned_data['identifier'].strip()
        user = (User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier), is_active=True)
                .exclude(email='').exclude(email__isnull=True).first())
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            link = request.build_absolute_uri(
                reverse('users:reset_password', args=[uid, default_token_generator.make_token(user)]))
            if not send_reset_link_email(user, link):
                messages.error(request, "L'envoi de l'email a échoué. Réessayez dans un instant.")
                return redirect('users:forgot_password')
        # Même réponse que le compte existe ou non : la page ne révèle pas les comptes.
        return redirect('users:forgot_password_sent')
    return render(request, 'users/forgot_password.html', {'form': form})


def forgot_password_sent_view(request):
    return render(request, 'users/forgot_password_sent.html')


def reset_password_view(request, uidb64, token):
    """Lien reçu par email : utilisable une seule fois (le jeton change avec le mot de passe), 1 heure."""
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uidb64)), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, 'users/reset_password.html', {'validlink': False})
    form = ManagerResetPasswordForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user.set_password(form.cleaned_data['new_password1'])
        user.save(update_fields=['password'])
        messages.success(request, 'Mot de passe modifié. Vous pouvez vous connecter.')
        return redirect('users:login')
    return render(request, 'users/reset_password.html', {'validlink': True, 'form': form, 'target': user})
