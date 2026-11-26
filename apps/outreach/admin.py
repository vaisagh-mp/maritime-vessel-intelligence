from django.contrib import admin

from .models import EmailLog, EmailTemplate


@admin.register(EmailTemplate)
class EmailTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "kind", "active", "sort_order", "updated_at")
    list_filter = ("kind", "active")
    search_fields = ("name", "subject", "body")


@admin.register(EmailLog)
class EmailLogAdmin(admin.ModelAdmin):
    list_display = ("sent_at", "to_email", "subject", "status", "sent_by", "vessel")
    list_filter = ("status",)
    search_fields = ("to_email", "subject")
    # A record of what was sent: it is never edited or added by hand.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
