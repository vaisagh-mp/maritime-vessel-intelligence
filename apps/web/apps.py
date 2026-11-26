from django.apps import AppConfig


class WebConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.web"
    label = "web"

    def ready(self):
        # Compatibility fix for Python 3.14 + Django BaseContext.__copy__
        import copy
        from django.template.context import BaseContext

        try:
            copy.copy(BaseContext())
        except AttributeError:
            def _base_context_copy(self):
                duplicate = self.__class__.__new__(self.__class__)
                duplicate.dicts = self.dicts[:]
                return duplicate

            BaseContext.__copy__ = _base_context_copy


