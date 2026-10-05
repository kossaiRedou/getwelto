import datetime

from django.contrib import admin, messages
from django.db.models import Count
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.html import format_html

from users.models import User
from . import services
from .models import EXPIRY_WARNING_DAYS, Account, Shop

STATUS_LABELS = {
    'pending': ('En attente', '#b45309', '#fef3c7'),
    'active': ('Actif', '#15803d', '#dcfce7'),
    'soon': ('Expire bientôt', '#9a3412', '#ffedd5'),
    'expired': ('Expiré', '#b91c1c', '#fee2e2'),
    'suspended': ('Suspendu', '#475569', '#e2e8f0'),
}


class StatusFilter(admin.SimpleListFilter):
    title = 'statut'
    parameter_name = 'statut'

    def lookups(self, request, model_admin):
        return [(key, label) for key, (label, _, _) in STATUS_LABELS.items()]

    def queryset(self, request, queryset):
        today = timezone.localdate()
        soon = today + datetime.timedelta(days=EXPIRY_WARNING_DAYS)
        value = self.value()
        if value == 'pending':
            return queryset.filter(is_active=False, active_until__isnull=True)
        if value == 'suspended':
            return queryset.filter(is_active=False, active_until__isnull=False)
        if value == 'expired':
            return queryset.filter(is_active=True, active_until__lt=today)
        if value == 'soon':
            return queryset.filter(is_active=True, active_until__gte=today, active_until__lte=soon)
        if value == 'active':
            return queryset.filter(is_active=True).exclude(active_until__lt=today)
        return queryset


class ShopInline(admin.TabularInline):
    model = Shop
    extra = 0
    fields = ('name', 'code', 'address', 'phone', 'is_active')
    show_change_link = True


class UserInline(admin.TabularInline):
    model = User
    fk_name = 'account'
    extra = 0
    fields = ('username', 'first_name', 'last_name', 'role', 'shop', 'phone', 'is_active', 'last_login')
    readonly_fields = ('username', 'first_name', 'last_name', 'role', 'shop', 'phone', 'last_login')
    can_delete = False
    verbose_name_plural = 'Utilisateurs (le gérant et ses employés)'

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = ('name', 'country', 'currency', 'manager_info', 'phone', 'status_badge',
                    'is_active', 'active_until', 'shops_used', 'max_shops', 'created_at')
    list_editable = ('is_active', 'active_until', 'max_shops')
    list_filter = (StatusFilter, 'country')
    search_fields = ('name', 'phone', 'email', 'users__username', 'users__phone')
    readonly_fields = ('created_at',)
    date_hierarchy = 'created_at'
    inlines = [ShopInline, UserInline]
    actions = ['activate_1', 'activate_3', 'activate_6', 'activate_12', 'suspend', 'delete_with_data']
    fieldsets = (
        ('Entreprise', {'fields': ('name', 'country', 'currency', 'phone', 'email', 'created_at')}),
        ('Abonnement', {'fields': ('is_active', 'active_until', 'max_shops'),
                        'description': "Le compte peut se connecter s'il est actif et que la date de fin "
                                       "n'est pas dépassée. Le gérant voit un rappel 7 jours avant la fin."}),
        ('Notes internes', {'fields': ('admin_notes',)}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_shops=Count('shops', distinct=True))

    @admin.display(description='Gérant')
    def manager_info(self, obj):
        manager = obj.manager
        return f'{manager.get_full_name() or manager.username} ({manager.username})' if manager else '—'

    @admin.display(description='Boutiques', ordering='n_shops')
    def shops_used(self, obj):
        return f'{obj.n_shops} / {obj.max_shops}'

    @admin.display(description='Statut')
    def status_badge(self, obj):
        label, color, background = STATUS_LABELS[obj.status]
        if obj.status == 'soon':
            label = f'{label} ({obj.days_left} j)'
        return format_html('<span style="padding:2px 8px;border-radius:9px;font-weight:600;color:{};background:{}">{}</span>',
                           color, background, label)

    # ------------------------------------------------------------ actions
    def _activate(self, request, queryset, months):
        for account in queryset:
            end = services.extend(account, months)
            self.message_user(request, f'{account.name} : actif jusqu\'au {end:%d/%m/%Y}.', messages.SUCCESS)

    @admin.action(description='Activer / prolonger de 1 mois')
    def activate_1(self, request, queryset):
        self._activate(request, queryset, 1)

    @admin.action(description='Activer / prolonger de 3 mois')
    def activate_3(self, request, queryset):
        self._activate(request, queryset, 3)

    @admin.action(description='Activer / prolonger de 6 mois')
    def activate_6(self, request, queryset):
        self._activate(request, queryset, 6)

    @admin.action(description='Activer / prolonger de 12 mois')
    def activate_12(self, request, queryset):
        self._activate(request, queryset, 12)

    @admin.action(description='Suspendre (bloquer la connexion)')
    def suspend(self, request, queryset):
        n = queryset.update(is_active=False)
        self.message_user(request, f'{n} compte(s) suspendu(s). Les données sont conservées.', messages.WARNING)

    @admin.action(description='Supprimer définitivement avec toutes les données…')
    def delete_with_data(self, request, queryset):
        if request.POST.get('confirm') == 'SUPPRIMER':
            names = [a.name for a in queryset]
            for account in queryset:
                services.delete_account(account)
            self.message_user(request, f'Supprimé(s) avec toutes leurs données : {", ".join(names)}.', messages.SUCCESS)
            return None
        return TemplateResponse(request, 'admin/accounts/confirm_delete.html', {
            **self.admin_site.each_context(request),
            'title': 'Supprimer définitivement',
            'accounts': queryset,
            'action': 'delete_with_data',
            'opts': self.model._meta,
            'wrong': 'confirm' in request.POST,
        })

    def has_delete_permission(self, request, obj=None):
        # La suppression simple échouerait (ventes protégées) : on passe par l'action dédiée.
        return False


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'account', 'address', 'phone', 'is_active', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('name', 'code', 'account__name')
    list_select_related = ('account',)
    readonly_fields = ('next_number', 'created_at')

    def has_delete_permission(self, request, obj=None):
        return False
