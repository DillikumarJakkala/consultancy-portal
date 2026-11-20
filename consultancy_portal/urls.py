from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth.views import LogoutView
from django.urls import include, path
from portal_core import views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", views.portal_login_view, name="login"),
    path("accounts/logout/", LogoutView.as_view(next_page="/accounts/login/"), name="logout"),
    path("dashboard/subvendor/", views.subvendor_dashboard_view, name="subvendor_dashboard"),
    path("", include("portal_core.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
