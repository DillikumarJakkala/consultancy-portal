from django.urls import path
from . import views

urlpatterns = [
    path("portal/admin/login/", views.portal_login_view, {"portal_type": "admin"}, name="portal_admin_login"),
    path("admin/login/", views.portal_login_view, {"portal_type": "admin"}, name="admin_portal_login"),
    path("login/admin/", views.portal_login_view, {"portal_type": "admin"}),
    path("partner/login/", views.portal_login_view, {"portal_type": "partner"}, name="partner_login"),
    path("", views.role_home, name="role_home"),
    path("dashboard/admin/", views.admin_dashboard_view, name="admin_dashboard"),
    path("dashboard/admin/profiles-breakdown/", views.profiles_breakdown_view, name="profiles_breakdown"),
    path("export/candidates.csv", views.export_candidates_csv_view, name="export_candidates_csv"),
    path("job-requisition/", views.job_requisition_view, name="job_requisition"),
]