from django.apps import AppConfig


class PortalCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'portal_core'

    def ready(self):
        from . import models  # noqa: F401
