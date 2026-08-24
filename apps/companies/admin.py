from django.contrib import admin

from .models import Company


@admin.register(Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "company_type", "priority", "email", "updated_at"]
    list_filter = ["company_type", "priority"]
    search_fields = ["name", "email"]
    ordering = ["name"]
