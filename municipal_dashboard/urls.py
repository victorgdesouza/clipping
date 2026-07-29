from django.urls import path

from . import views


app_name = "municipal_dashboard"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/overview/", views.api_overview, name="api_overview"),
    path("api/indicators/<slug:slug>/", views.api_indicator_detail, name="api_indicator_detail"),
    path("api/freshness/", views.api_freshness, name="api_freshness"),
    path("api/measurements/", views.api_measurements, name="api_measurements"),
]
