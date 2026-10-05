from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AppSetting, User, UserProfile


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profil'
    fields = ('address', 'birth_date', 'hire_date', 'salary', 'notes')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Utilisateurs de tous les comptes clients (l'admin est réservé au propriétaire du SaaS)."""
    inlines = (UserProfileInline,)
    list_display = ('username', 'get_full_name', 'account', 'role', 'shop', 'phone', 'is_active', 'last_login')
    list_filter = ('role', 'is_active', 'account')
    list_select_related = ('account', 'shop')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone', 'account__name')
    ordering = ('-created_at',)
    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Informations personnelles', {'fields': ('first_name', 'last_name', 'email', 'phone')}),
        ('Compte client', {'fields': ('account', 'role', 'shop'),
                           'description': "Laisser le compte vide uniquement pour le propriétaire du SaaS."}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
        ('Dates', {'fields': ('last_login', 'date_joined', 'created_at', 'created_by')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',),
                'fields': ('username', 'first_name', 'last_name', 'email', 'phone', 'account', 'role', 'shop',
                           'password1', 'password2')}),
    )
    readonly_fields = ('created_at', 'created_by', 'last_login', 'date_joined')

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ('account', 'company_name', 'low_stock_threshold', 'updated_at')
    search_fields = ('account__name', 'company_name')
