import django_filters

from .models import Company


class CompanyFilter(django_filters.FilterSet):
    """FilterSet for Company with support for annotated vessel_count field.

    Supports numeric range filtering on the distinct vessel count
    (annotated on the queryset, not a stored model field):
        ?vessel_count=5          — exact match
        ?vessel_count_lte=2      — small fleet operators
        ?vessel_count_gte=10     — major fleet operators
    """

    vessel_count = django_filters.NumberFilter(field_name="vessel_count")
    vessel_count_lte = django_filters.NumberFilter(
        field_name="vessel_count", lookup_expr="lte"
    )
    vessel_count_gte = django_filters.NumberFilter(
        field_name="vessel_count", lookup_expr="gte"
    )

    class Meta:
        model = Company
        fields = ["company_type", "priority"]
