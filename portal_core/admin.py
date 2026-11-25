from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm
from .models import Candidate, JobAssignment, JobDescription, Notification, User

ALLOWED_USER_ROLES = [
    ("ADMIN", "Admin"),
    ("SUBVENDOR", "Subvendor"),
]


class CleanUserCreationForm(UserCreationForm):
    role = forms.ChoiceField(choices=ALLOWED_USER_ROLES, initial="SUBVENDOR", required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "role")


class CleanUserChangeForm(forms.ModelForm):
    role = forms.ChoiceField(choices=ALLOWED_USER_ROLES, required=True)

    class Meta:
        model = User
        fields = ("username", "role", "is_active")


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = CleanUserChangeForm
    add_form = CleanUserCreationForm
    list_display = ("username", "role", "is_active")
    list_filter = ("role", "is_active")
    search_fields = ("username",)
    ordering = ("username",)
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Role & Status", {"fields": ("role", "is_active")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("username", "role", "password1", "password2"),
        }),
    )

    def save_model(self, request, obj, form, change):
        if obj.role == "ADMIN":
            obj.is_staff = True
            obj.is_superuser = True
        else:
            obj.is_staff = False
            obj.is_superuser = False
        super().save_model(request, obj, form, change)

class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "first_name", "last_name")
    ordering = ("username",)
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Role Information", {"fields": ("role",)}),
    )
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Role Information", {"fields": ("role",)}),
    )

from django import forms
from django.contrib import admin


class JobDescriptionAdminForm(forms.ModelForm):
    class Meta:
        model = JobDescription
        exclude = ("salary",)


@admin.register(JobDescription)
class JobDescriptionAdmin(admin.ModelAdmin):
    form = JobDescriptionAdminForm
    list_display = (
        "title",
        "company_name",
        "positions_needed",
        "experience_required",
        "salary_range",
        "urgency",
        "location",
        "is_active",
    )
    list_editable = (
        "company_name",
        "positions_needed",
        "experience_required",
        "salary_range",
        "urgency",
        "is_active",
    )
    list_filter = ("experience_required", "salary_range", "urgency", "is_active")
    search_fields = ("title", "company_name", "location")


@admin.register(JobAssignment)
class JobAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "job",
        "assigned_to",
        "profiles_requested",
        "job_positions_needed",
        "remarks",
        "assigned_at",
    )
    list_editable = ("profiles_requested",)
    fields = ("job", "assigned_to", "profiles_requested", "remarks")
    list_filter = ("assigned_to", "job")
    search_fields = ("job__title", "job__company_name", "assigned_to__username", "remarks")

    @admin.display(description="Total Positions Needed")
    def job_positions_needed(self, obj):
        return obj.job.positions_needed if obj and obj.job else "-"


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("__str__",)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "message", "is_read", "created_at")
    list_filter = ("is_read", "recipient", "created_at")
    search_fields = ("recipient__username", "message")