from django.urls import path
from . import views

urlpatterns = [
    path("", views.role_home, name="role_home"),
    path("dashboard/admin/", views.admin_dashboard_view, name="admin_dashboard"),
    path("dashboard/admin/profiles-breakdown/", views.profiles_breakdown_view, name="profiles_breakdown"),
    path("export/candidates.csv", views.export_candidates_csv_view, name="export_candidates_csv"),
]
