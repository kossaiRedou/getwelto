from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import User, UserProfile, AppSetting


class UserProfileInline(admin.StackedInline):
    """Inline pour le profil utilisateur"""
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Profil'
    fields = ('address', 'birth_date', 'hire_date', 'salary', 'notes')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Interface admin pour la gestion des utilisateurs"""
    
    inlines = (UserProfileInline,)
    
    list_display = (
        'username', 'get_full_name', 'email', 'role', 'is_active', 
        'created_by', 'created_at', 'get_status_badge'
    )
    
    list_filter = ('role', 'is_active', 'created_at', 'created_by')
    
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone')
    
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {
            'fields': ('username', 'password')
        }),
        ('Informations personnelles', {
            'fields': ('first_name', 'last_name', 'email', 'phone')
        }),
        ('Permissions', {
            'fields': ('role', 'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Dates importantes', {
            'fields': ('last_login', 'date_joined', 'created_at', 'created_by')
        }),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'email', 'phone', 'role', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('created_at', 'created_by', 'last_login', 'date_joined')
    
    def get_status_badge(self, obj):
        """Afficher un badge pour le statut"""
        if obj.is_active:
            return format_html(
                '<span class="badge bg-success">Actif</span>'
            )
        else:
            return format_html(
                '<span class="badge bg-danger">Inactif</span>'
            )
    get_status_badge.short_description = 'Statut'
    
    def get_role_badge(self, obj):
        """Afficher un badge pour le rôle"""
        if obj.role == 'manager':
            return format_html(
                '<span class="badge bg-primary">Manager</span>'
            )
        else:
            return format_html(
                '<span class="badge bg-secondary">Employé</span>'
            )
    get_role_badge.short_description = 'Rôle'
    
    def save_model(self, request, obj, form, change):
        """Sauvegarder le modèle avec le créateur"""
        if not change:  # Nouvelle création
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
    
    def get_queryset(self, request):
        """Filtrer les utilisateurs selon les permissions"""
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            # Les managers ne voient que les utilisateurs qu'ils ont créés
            if request.user.is_manager():
                qs = qs.filter(created_by=request.user)
            else:
                # Les employés ne voient que leur propre compte
                qs = qs.filter(id=request.user.id)
        return qs
    
    def has_add_permission(self, request):
        """Vérifier les permissions d'ajout"""
        return request.user.is_manager() or request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Vérifier les permissions de modification"""
        if obj is None:
            return request.user.is_manager() or request.user.is_superuser
        return (request.user.is_manager() and obj.created_by == request.user) or request.user.is_superuser
    
    def has_delete_permission(self, request, obj=None):
        """Vérifier les permissions de suppression"""
        if obj is None:
            return request.user.is_manager() or request.user.is_superuser
        # Empêcher la suppression de son propre compte
        if obj == request.user:
            return False
        return (request.user.is_manager() and obj.created_by == request.user) or request.user.is_superuser


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Interface admin pour les profils utilisateurs"""
    
    list_display = ('user', 'hire_date', 'salary', 'get_full_address')
    
    list_filter = ('hire_date',)
    
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'user__email')
    
    readonly_fields = ('user',)
    
    def get_full_address(self, obj):
        """Afficher l'adresse complète"""
        if obj.address:
            return obj.address[:50] + '...' if len(obj.address) > 50 else obj.address
        return '-'
    get_full_address.short_description = 'Adresse'
    
    def has_add_permission(self, request):
        """Seuls les managers peuvent ajouter des profils"""
        return request.user.is_manager() or request.user.is_superuser
    
    def has_change_permission(self, request, obj=None):
        """Vérifier les permissions de modification"""
        if obj is None:
            return request.user.is_manager() or request.user.is_superuser
        return (request.user.is_manager() and obj.user.created_by == request.user) or request.user.is_superuser
    
    def has_delete_permission(self, request, obj=None):
        """Vérifier les permissions de suppression"""
        if obj is None:
            return request.user.is_manager() or request.user.is_superuser
        return (request.user.is_manager() and obj.user.created_by == request.user) or request.user.is_superuser


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ('currency_label', 'low_stock_threshold', 'updated_at')