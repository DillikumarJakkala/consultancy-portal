from django.contrib import messages
from django.contrib.auth import get_user_model
import csv
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from .models import Candidate, JobAssignment, JobDescription, Notification
from .forms import CandidateSubmissionForm


def _filtered_candidates(request):
    queryset = Candidate.objects.select_related("job", "submitted_by").all()
    search = request.GET.get("search", "").strip()
    status = request.GET.get("status", "").strip()

    if search:
        queryset = queryset.filter(
            Q(full_name__icontains=search)
            | Q(email__icontains=search)
            | Q(phone__icontains=search)
        )

    if status:
        queryset = queryset.filter(status=status)

    return queryset, search, status


def _build_subvendor_quota_rows(assignments):
    all_candidates = list(
        Candidate.objects.select_related("job", "submitted_by").order_by("-created_at")
    )
    rows = []
    for a in assignments:
        job_id = getattr(a, "job_id", None)
        subvendor_id = getattr(a, "assigned_to_id", None)
        sent_count = sum(
            1 for c in all_candidates
            if c.job_id == job_id and c.submitted_by_id == subvendor_id
        )
        requested_count = getattr(a, "profiles_requested", 0) or 0
        remaining_count = max(requested_count - sent_count, 0)
        rows.append({
            "assignment": a,
            "subvendor_name": a.assigned_to.username if a.assigned_to else "-",
            "job_title": a.job.title if a.job else "-",
            "company_name": (a.job.company_name if a.job and a.job.company_name else "-"),
            "requested": requested_count,
            "sent": sent_count,
            "remaining": remaining_count,
            "remarks": a.remarks or "-",
            "assigned_at": a.assigned_at,
        })
    total_requested = sum(r["requested"] for r in rows)
    total_sent = sum(r["sent"] for r in rows)
    total_remaining = sum(r["remaining"] for r in rows)
    return rows, total_requested, total_sent, total_remaining


def _build_unique_subvendor_groups(quota_rows):
    UserModel = get_user_model()
    subvendors = list(
        UserModel.objects.filter(role="SUBVENDOR").order_by("username", "id")
    )
    grouped = {}

    for u in subvendors:
        grouped[u.pk] = {
            "subvendor_key": str(u.pk),
            "subvendor_name": u.username,
            "jobs_count": 0,
            "total_assigned": 0,
            "total_received": 0,
            "total_pending": 0,
            "items": [],
        }

    for r in quota_rows:
        assign_obj = r["assignment"]
        sub_id = getattr(assign_obj, "assigned_to_id", None)
        if sub_id is None:
            continue
        if sub_id not in grouped:
            sub_user = getattr(assign_obj, "assigned_to", None)
            grouped[sub_id] = {
                "subvendor_key": str(sub_id),
                "subvendor_name": sub_user.username if sub_user else r["subvendor_name"],
                "jobs_count": 0,
                "total_assigned": 0,
                "total_received": 0,
                "total_pending": 0,
                "items": [],
            }
        g = grouped[sub_id]
        g["jobs_count"] += 1
        g["total_assigned"] += r["requested"]
        g["total_received"] += r["sent"]
        g["total_pending"] += r["remaining"]
        g["items"].append(r)

    return list(grouped.values())


@login_required
def admin_dashboard_view(request):
    if request.method == "POST":
        candidate_id = request.POST.get("candidate_id")
        new_status = request.POST.get("status")
        valid_statuses = {key for key, _ in Candidate.STATUS_CHOICES}
        if candidate_id and new_status in valid_statuses:
            candidate = get_object_or_404(Candidate, pk=candidate_id)
            candidate.status = new_status
            candidate.save(update_fields=["status", "updated_at"])
        return redirect(request.get_full_path() or "admin_dashboard")

    jobs = list(JobDescription.objects.prefetch_related("assignments__assigned_to").order_by("-id"))
    assignments = list(
        JobAssignment.objects.select_related("job", "assigned_to").order_by("-assigned_at", "-id")
    )
    notifications = list(
        Notification.objects.select_related("recipient", "assignment__job").order_by("-created_at")[:10]
    )

    job_rows = []
    for j in jobs:
        j_assignments = list(j.assignments.all())
        assigned_names = [
            f"{a.assigned_to.username} ({a.profiles_requested})"
            for a in j_assignments
            if getattr(a, "assigned_to", None)
        ]
        exp_label = (
            j.get_experience_required_display()
            if hasattr(j, "get_experience_required_display")
            else getattr(j, "experience_required", "-")
        )
        sal_label = (
            j.get_salary_range_display()
            if hasattr(j, "get_salary_range_display")
            else (getattr(j, "salary_range", "") or getattr(j, "salary", "-"))
        )
        urg_label = (
            j.get_urgency_display()
            if hasattr(j, "get_urgency_display")
            else getattr(j, "urgency", "-")
        )
        job_rows.append({
            "obj": j,
            "title": getattr(j, "title", "-"),
            "company_name": getattr(j, "company_name", "") or "-",
            "positions_needed": getattr(j, "positions_needed", 0),
            "experience_label": exp_label or "-",
            "salary_label": sal_label or "-",
            "urgency_label": urg_label or "-",
            "urgency_raw": getattr(j, "urgency", ""),
            "location": getattr(j, "location", "") or "-",
            "is_active": getattr(j, "is_active", True),
            "assigned_summary": ", ".join(assigned_names) if assigned_names else "Unassigned",
        })

    active_jobs_count = sum(1 for j in jobs if getattr(j, "is_active", True))
    quota_rows, total_profiles_requested, total_profiles_sent, total_profiles_remaining = _build_subvendor_quota_rows(assignments)
    subvendor_groups = _build_unique_subvendor_groups(quota_rows)

    candidates, search, status = _filtered_candidates(request)
    context = {
        "candidates": candidates,
        "search": search,
        "selected_status": status,
        "status_choices": Candidate.STATUS_CHOICES,
        "job_rows": job_rows,
        "assignments": assignments,
        "notifications": notifications,
        "total_jobs_count": len(jobs),
        "active_jobs_count": active_jobs_count,
        "total_assignments_count": len(assignments),
        "total_profiles_requested": total_profiles_requested,
        "total_profiles_sent": total_profiles_sent,
        "total_profiles_remaining": total_profiles_remaining,
        "quota_rows": quota_rows,
        "subvendor_groups": subvendor_groups,
    }
    return render(request, "portal_core/admin_dashboard.html", context)


@login_required
def profiles_breakdown_view(request):
    assignments = list(
        JobAssignment.objects.select_related("job", "assigned_to").order_by("-assigned_at", "-id")
    )
    quota_rows, total_requested, total_sent, total_remaining = _build_subvendor_quota_rows(assignments)
    context = {
        "quota_rows": quota_rows,
        "total_requested": total_requested,
        "total_sent": total_sent,
        "total_remaining": total_remaining,
    }
    return render(request, "portal_core/profiles_breakdown.html", context)


@login_required
def subvendor_dashboard_view(request):
    assignments = list(
        JobAssignment.objects.select_related("job", "assigned_to")
        .filter(assigned_to=request.user)
        .order_by("-assigned_at", "-id")
    )

    my_candidates = list(
        Candidate.objects.select_related("job")
        .filter(submitted_by=request.user)
        .order_by("-created_at", "-id")
    )

    sent_by_job = {}
    for c in my_candidates:
        if c.job_id is not None:
            sent_by_job[c.job_id] = sent_by_job.get(c.job_id, 0) + 1

    assignment_rows = []
    for a in assignments:
        requested = getattr(a, "profiles_requested", 0) or 0
        sent = sent_by_job.get(a.job_id, 0)
        remaining = max(requested - sent, 0)
        assignment_rows.append({
            "assignment": a,
            "job": a.job,
            "requested": requested,
            "sent": sent,
            "remaining": remaining,
            "can_submit": remaining > 0 if requested > 0 else True,
        })

    form = CandidateSubmissionForm(subvendor=request.user)

    if request.method == "POST":
        if request.POST.get("submit_candidate"):
            form = CandidateSubmissionForm(request.POST, request.FILES, subvendor=request.user)
            if form.is_valid():
                candidate = form.save(commit=False)
                candidate.submitted_by = request.user
                candidate.status = "SUBMITTED_BY_SUBVENDOR"
                candidate.save()
                messages.success(
                    request,
                    f"Submitted profile for {candidate.full_name} under {candidate.job.title}.",
                )
                return redirect("subvendor_dashboard")
        else:
            notif_id = request.POST.get("mark_read_id")
            if notif_id:
                Notification.objects.filter(pk=notif_id, recipient=request.user).update(is_read=True)
            elif request.POST.get("mark_all_read"):
                Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True)
            return redirect("subvendor_dashboard")

    unread_alerts = list(
        Notification.objects.filter(recipient=request.user, is_read=False).order_by("-created_at")
    )
    all_alerts = list(
        Notification.objects.filter(recipient=request.user).order_by("-created_at")[:15]
    )
    total_profiles_assigned = sum(r["requested"] for r in assignment_rows)
    total_profiles_sent = sum(r["sent"] for r in assignment_rows)
    total_profiles_remaining = sum(r["remaining"] for r in assignment_rows)

    context = {
        "assignments": assignments,
        "assignment_rows": assignment_rows,
        "form": form,
        "my_candidates": my_candidates,
        "unread_alerts": unread_alerts,
        "all_alerts": all_alerts,
        "total_assigned_jobs": len(assignment_rows),
        "total_profiles_assigned": total_profiles_assigned,
        "total_profiles_sent": total_profiles_sent,
        "total_profiles_remaining": total_profiles_remaining,
    }
    return render(request, "portal_core/subvendor_dashboard.html", context)
@login_required
def export_candidates_csv_view(request):
    candidates, _, _ = _filtered_candidates(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="candidates_export.csv"'

    writer = csv.writer(response)
    writer.writerow(["Candidate Name", "Job Title", "Submitted By", "Status", "Email", "Phone"])
    for c in candidates:
        writer.writerow([
            c.full_name,
            c.job.title if c.job else "",
            c.submitted_by.username if c.submitted_by else "",
            c.get_status_display(),
            c.email,
            c.phone,
        ])
    return response


def role_home(request):
    if request.user.is_authenticated:
        if getattr(request.user, "is_superuser", False) or getattr(request.user, "role", "") == "ADMIN" or (hasattr(request.user, "is_admin_role") and request.user.is_admin_role()):
            return redirect("admin_dashboard")
        if getattr(request.user, "role", "") == "SUBVENDOR" or (hasattr(request.user, "is_subvendor_role") and request.user.is_subvendor_role()):
            return redirect("subvendor_dashboard")
    return redirect("login")


from django.contrib.auth import login as auth_login
from django.contrib.auth.forms import AuthenticationForm


def _redirect_by_role(user):
    if getattr(user, "is_superuser", False) or getattr(user, "role", "") == "ADMIN" or (hasattr(user, "is_admin_role") and user.is_admin_role()):
        return redirect("admin_dashboard")
    if getattr(user, "role", "") == "SUBVENDOR" or (hasattr(user, "is_subvendor_role") and user.is_subvendor_role()):
        return redirect("subvendor_dashboard")
    return redirect("subvendor_dashboard")


PORTAL_TITLES = {
    "admin": "Admin Portal Login",
    "partner": "Sub-Vendor Partner Login",
    "general": "Consultancy Portal Login",
}


def portal_login_view(request, portal_type="general"):
    if request.user.is_authenticated:
        return _redirect_by_role(request.user)

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.get_user()
        auth_login(request, user)
        return _redirect_by_role(user)

    normalized_type = portal_type if portal_type in PORTAL_TITLES else "general"
    context = {
        "form": form,
        "portal_type": normalized_type,
        "portal_title": PORTAL_TITLES[normalized_type],
    }
    return render(request, "registration/login.html", context)