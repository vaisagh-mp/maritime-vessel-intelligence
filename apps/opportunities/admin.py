from django.conf import settings
from django.contrib import admin

from .models import Opportunity, OpportunityNote, OpportunityStageChange


class ScoreBandFilter(admin.SimpleListFilter):
    """Admin sidebar filter that lets users filter Opportunities by priority
    band (HOT/HIGH/MEDIUM/LOW) without needing a stored column — translates
    the band label into a score-range query."""

    title = "Score Band"
    parameter_name = "band"

    def lookups(self, request, model_admin):
        return [(label, label) for _, label in settings.SCORE_BANDS]

    def queryset(self, request, queryset):
        value = self.value()
        if not value:
            return queryset

        bands = settings.SCORE_BANDS
        for i, (threshold, label) in enumerate(bands):
            if label == value:
                upper = bands[i - 1][0] if i > 0 else None
                if upper is not None:
                    return queryset.filter(score__gte=threshold, score__lt=upper)
                return queryset.filter(score__gte=threshold)

        return queryset


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ["vessel", "port", "zone", "stage", "score", "display_band", "eta", "detected_at"]
    list_filter = ["stage", "zone", "port", ScoreBandFilter]
    search_fields = ["vessel__name", "vessel__mmsi", "port__name"]
    autocomplete_fields = ["vessel", "port"]
    date_hierarchy = "detected_at"
    ordering = ["-score"]

    @admin.display(description="Band", ordering="score")
    def display_band(self, obj):
        return obj.band


@admin.register(OpportunityNote)
class OpportunityNoteAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "author", "created_at"]
    search_fields = ["opportunity__vessel__name", "text", "author__username"]
    ordering = ["-created_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OpportunityStageChange)
class OpportunityStageChangeAdmin(admin.ModelAdmin):
    list_display = ["opportunity", "from_stage", "to_stage", "changed_by", "changed_at"]
    search_fields = ["opportunity__vessel__name", "changed_by__username"]
    ordering = ["-changed_at"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

