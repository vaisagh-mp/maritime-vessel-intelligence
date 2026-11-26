from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .company_views import CompanyDetailPageView, CompanyListPageView
from .outreach_views import EmailLogPageView, EmailTemplatesPageView
from .views import (
    BusinessDevelopersView,
    HomeView,
    LatestArrivalsView,
    LeadDetailView,
    PriorityIndexView,
    PriorityView,
    VesselDetailView,
)

app_name = "web"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
    path("priority/", PriorityIndexView.as_view(), name="priority_index"),
    path("priority/<str:zone>/", PriorityView.as_view(), name="priority"),
    path("companies/", CompanyListPageView.as_view(), name="companies"),
    path("companies/<int:pk>/", CompanyDetailPageView.as_view(), name="company_detail"),
    path("latest/", LatestArrivalsView.as_view(), name="latest"),
    path("email-templates/", EmailTemplatesPageView.as_view(), name="email_templates"),
    path("email-log/", EmailLogPageView.as_view(), name="email_log"),
    path("business-developers/", BusinessDevelopersView.as_view(), name="business_developers"),
    path("vessels/<int:pk>/", VesselDetailView.as_view(), name="vessel"),
    path("leads/<int:pk>/", LeadDetailView.as_view(), name="lead"),
    path(
        "login/",
        LoginView.as_view(
            template_name="web/login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path(
        "logout/",
        LogoutView.as_view(),
        name="logout",
    ),
]
