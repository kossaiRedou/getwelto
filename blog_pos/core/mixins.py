"""
Mixins communs aux modèles métier WELTO.

Chaque modèle métier porte :
- sync_uuid : identifiant universel stable, indépendant des clés primaires
  auto-incrémentées locales.
- updated_at : horodatage de dernière modification.
"""
import uuid

from django.db import models


class SyncableMixin(models.Model):
    sync_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        abstract = True


class SyncUUIDMixin(models.Model):
    """Variante pour les modèles possédant déjà leur propre updated_at."""
    sync_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        abstract = True
