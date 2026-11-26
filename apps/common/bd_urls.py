from django.urls import path

from .bd_views import (
    BusinessDeveloperDetailView,
    BusinessDeveloperListCreateView,
    BusinessDeveloperPasswordView,
)

urlpatterns = [
    path("", BusinessDeveloperListCreateView.as_view(), name="bd-list"),
    path("<int:pk>/", BusinessDeveloperDetailView.as_view(), name="bd-detail"),
    path("<int:pk>/reset-password/", BusinessDeveloperPasswordView.as_view(), name="bd-reset-password"),
]
