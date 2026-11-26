from django.urls import path

from .views import (HistoryView, LogView, ManageTemplateDetailView, ManageTemplatesView, PreviewView, SendView,
                    TemplateListView)

urlpatterns = [
    path("templates/", TemplateListView.as_view(), name="outreach-templates"),
    path("preview/", PreviewView.as_view(), name="outreach-preview"),
    path("send/", SendView.as_view(), name="outreach-send"),
    path("log/", LogView.as_view(), name="outreach-log"),
    path("manage/templates/", ManageTemplatesView.as_view(), name="outreach-manage-templates"),
    path("manage/templates/<int:pk>/", ManageTemplateDetailView.as_view(), name="outreach-manage-template"),
    path("history/", HistoryView.as_view(), name="outreach-history"),
]
