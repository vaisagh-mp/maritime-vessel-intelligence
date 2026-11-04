from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.common.pagination import StandardResultsSetPagination
from apps.common.permissions import IsAdminOrBDManagerReadOnly

from .filters import CompanyFilter
from .models import Company
from .serializers import CompanySerializer

# Valid ordering fields for the list endpoint.
_VALID_ORDERING = {"vessel_count", "-vessel_count", "name", "-name", "priority", "-priority"}


def _annotated_queryset():
    """Return a Company queryset annotated with distinct vessel count."""
    return Company.objects.annotate(
        vessel_count=Count("vessel_relationships__vessel", distinct=True)
    ).order_by("name")


class CompanyListCreateAPIView(APIView):
    """Full read/write — Admin-only writes; BD Managers can read."""

    permission_classes = [IsAdminOrBDManagerReadOnly]

    def get(self, request):
        qs = _annotated_queryset()

        # Apply django-filter filterset (company_type, priority, vessel_count*)
        filterset = CompanyFilter(request.GET, queryset=qs)
        if filterset.is_valid():
            qs = filterset.qs

        # Text search
        search = request.query_params.get("search")
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(email__icontains=search))

        # Ordering
        ordering = request.query_params.get("ordering")
        if ordering and ordering in _VALID_ORDERING:
            qs = qs.order_by(ordering)

        paginator = StandardResultsSetPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        if page is not None:
            serializer = CompanySerializer(page, many=True)
            return paginator.get_paginated_response(serializer.data)
        serializer = CompanySerializer(qs, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = CompanySerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompanyDetailAPIView(APIView):
    """Full read/write — Admin-only writes; BD Managers can read."""

    permission_classes = [IsAdminOrBDManagerReadOnly]

    def get_object(self, pk):
        # Use annotated queryset so vessel_count is available on GET detail
        qs = _annotated_queryset()
        return get_object_or_404(qs, pk=pk)

    def get(self, request, pk):
        company = self.get_object(pk)
        serializer = CompanySerializer(company)
        return Response(serializer.data)

    def put(self, request, pk):
        company = self.get_object(pk)
        serializer = CompanySerializer(company, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        company = self.get_object(pk)
        serializer = CompanySerializer(company, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        company = get_object_or_404(Company, pk=pk)
        company.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
