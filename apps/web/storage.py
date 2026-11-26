"""
apps/web/storage.py
Custom static files storage for production hashed asset delivery.
"""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class AggregatedManifestStaticFilesStorage(ManifestStaticFilesStorage):
    """ManifestStaticFilesStorage with JS module import aggregation enabled.

    Rewrites relative import specifiers in JavaScript ES modules to hashed asset filenames
    during collectstatic.
    """

    support_js_module_import_aggregation = True

