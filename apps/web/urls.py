from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path

from .views import HomeView

app_name = "web"

urlpatterns = [
    path("", HomeView.as_view(), name="home"),
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

