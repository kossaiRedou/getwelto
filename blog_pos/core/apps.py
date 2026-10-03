from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Noyau WELTO'

    def ready(self):
        from . import throttle  # noqa: F401 (branche les signaux de connexion)
