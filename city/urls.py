from django.urls import path

from . import views

urlpatterns = [
    path("", views.index, name="index"),
    path("map/", views.dashboard, name="dashboard"),
    path("api/reports/", views.api_reports),
    path("api/reports/create/", views.api_report_create),
    path("api/reports/<int:pk>/confirm/", views.api_confirm),
    path("api/segment/", views.api_segment),
    path("api/route/", views.api_route),
    path("api/answer/", views.api_answer),
    path("api/detour/", views.api_detour),
    path("api/warm/", views.api_warm),
    path("api/trip/<str:trip_id>/", views.api_trip),
    path("api/reports/<int:pk>/", views.api_report_detail),
    path("api/demo/reset/", views.api_demo_reset),
]
