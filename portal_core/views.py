import csv
import json
import os
import urllib.request

from django.contrib import messages
from django.contrib.auth import get_user_model, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .forms import CandidateSubmissionForm
from .models import Candidate, JobAssignment, JobDescription, Notification


DAY_URGENCY_CHOICES = [
    ("1_DAY", "1 Day"),
    ("2_DAYS", "2 Days"),
    ("3_DAYS", "3 Days"),
    ("4_DAYS", "4 Days"),
    ("5_DAYS", "5 Days"),
    ("6_DAYS", "6 Days"),
    ("7_DAYS", "7 Days"),
    ("CUSTOM_DAYS", "Custom Days (Manual)"),
]

PRESET_DAYS_MAP = {
    "1_DAY": 1,
    "2_DAYS": 2,
    "3_DAYS": 3,
    "4_DAYS": 4,
    "5_DAYS": 5,
    "6_DAYS": 6,
    "7_DAYS": 7,
}


def _resolve_urgency_timeline(urgency_choice: str, custom_days_raw: str):
    valid_urgencies = {k for k, _ in JobDescription.URGENCY_CHOICES}
    choice = (urgency_choice or "3_DAYS").strip()

    if choice == "CUSTOM_DAYS":
        try:
            days = max(1, int((custom_days_raw or "").strip()))
        except (TypeError, ValueError):
            days = 3
        label = f"{days} Day" if days == 1 else f"{days} Days"
    else:
        days = PRESET_DAYS_MAP.get(choice, 3)
        label = f"{days} Day" if days == 1 else f"{days} Days"

    if days <= 2:
        mapped_urgency = "URGENT"
    elif days <= 5:
        mapped_urgency = "HIGH"
    else:
        mapped_urgency = "NORMAL"

    if mapped_urgency not in valid_urgencies:
        mapped_urgency = next(iter(valid_urgencies), "NORMAL")

    return choice, days, label, mapped_urgency


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


def _extract_candidate_resume_text(candidate) -> str:
    parts = []
    for field_name in ("resume_text", "skills", "experience_summary", "notes", "cover_note"):
        val = getattr(candidate, field_name, "")
        if isinstance(val, str) and val.strip():
            parts.append(val.strip())

    resume_file = getattr(candidate, "resume", None)
    if resume_file and getattr(resume_file, "name", ""):
        parts.append(f"Uploaded Resume File: {resume_file.name}")
        try:
            if resume_file.name.lower().endswith((".txt", ".md", ".csv")):
                with resume_file.open("rb") as f:
                    raw = f.read(12000).decode("utf-8", errors="ignore").strip()
                    if raw:
                        parts.append(raw)
        except Exception:
            pass

    return "\n".join(parts).strip()


def _screen_candidate_with_ai(candidate, job) -> str:
    cand_name = getattr(candidate, "full_name", "Candidate")
    job_title = getattr(job, "title", "Assigned Role") if job else "Assigned Role"
    job_details = (getattr(job, "details", "") or "").strip() if job else ""
    resume_text = _extract_candidate_resume_text(candidate)

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        prompt = (
            f"You are a technical recruiter screening a candidate for '{job_title}'.\n"
            f"Candidate: {cand_name}\n"
            f"Job Requirements:\n{job_details[:1500] or 'Standard role requirements'}\n\n"
            f"Candidate Resume / Profile Info:\n{resume_text[:2500] or 'No resume text provided'}\n\n"
            "Return a concise plain-text review with:\n"
            "1) Fit Score / Verdict (Strong Fit, Moderate Fit, or Low Fit)\n"
            "2) Key Strengths / Matches\n"
            "3) Missing Skills or Gaps to Verify\n"
            "4) Suggested Next Step"
        )
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={gemini_key}"
            )
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates_out = data.get("candidates") or []
                parts = ((candidates_out[0].get("content") or {}).get("parts") or []) if candidates_out else []
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                if text:
                    return text
        except Exception:
            pass

    jd_words = {
        w.strip(".,()[]{}:;\"'").lower()
        for w in job_details.split()
        if len(w.strip(".,()[]{}:;\"'")) >= 3
    }
    res_words = {
        w.strip(".,()[]{}:;\"'").lower()
        for w in resume_text.split()
        if len(w.strip(".,()[]{}:;\"'")) >= 3
    }
    overlap = sorted(jd_words & res_words)[:8]
    if not resume_text:
        return (
            f"Screening Summary for {cand_name} ({job_title}):\n"
            f"- Fit Verdict: Needs Resume / Profile Details\n"
            f"- Note: No resume text or readable resume file was found on this candidate record.\n"
            f"- Next Step: Request an updated resume/CV before advancing interview stages."
        )
    match_line = ", ".join(overlap) if overlap else "General domain alignment"
    return (
        f"Screening Summary for {cand_name} ({job_title}):\n"
        f"- Fit Verdict: Preliminary Review Ready (Fallback Mode)\n"
        f"- Matched Keywords: {match_line}\n"
        f"- Next Step: Review full resume against '{job_title}' requirements and confirm role experience."
    )


@login_required
def admin_dashboard_view(request):
    if request.method == "POST":
        screen_candidate_id = request.POST.get("screen_candidate_id")
        if screen_candidate_id:
            candidate = get_object_or_404(
                Candidate.objects.select_related("job"), pk=screen_candidate_id
            )
            review_text = _screen_candidate_with_ai(candidate, candidate.job)
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"ok": True, "candidate_id": candidate.pk, "review": review_text})
            messages.info(request, review_text)
            return redirect(request.get_full_path() or "admin_dashboard")

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
        return _redirect_by_role(request)

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


def _generate_ai_job_details(
    title: str,
    company_name: str,
    location: str,
    experience_label: str,
    salary_label: str,
    urgency_label: str,
) -> str:
    role_title = title.strip() or "Software / Operations Role"
    company = company_name.strip() or "Client Organization"
    loc = location.strip() or "Hybrid / On-site"

    prompt = (
        f"Write a clear, concise job description and key required skills for '{role_title}' "
        f"at '{company}' (Location: {loc}, Experience: {experience_label}, "
        f"Compensation: {salary_label}, Hiring Timeline: {urgency_label}). "
        f"Include responsibilities and required technical/domain skills in plain text."
    )

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        try:
            url = (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-2.5-flash:generateContent?key={gemini_key}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt}]}]
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates") or []
                parts = ((candidates[0].get("content") or {}).get("parts") or []) if candidates else []
                text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                if text:
                    return text
        except Exception:
            pass

    return (
        f"Role Overview: {company} is hiring for {role_title} ({loc}).\n"
        f"Hiring Timeline: {urgency_label} | Experience Target: {experience_label} | Compensation Band: {salary_label}.\n"
        f"Key Responsibilities:\n"
        f"- Deliver day-to-day responsibilities for {role_title} with clear ownership and timely reporting.\n"
        f"- Collaborate with team leads and stakeholders to meet delivery and quality targets.\n"
        f"- Document workflows, resolve issues promptly, and maintain production reliability.\n"
        f"Required Skills:\n"
        f"- Strong fundamentals relevant to {role_title}, clear communication, and problem-solving."
    )


def job_requisition_view(request):
    selected_urgency_choice = "3_DAYS"
    selected_custom_days = ""

    if request.method == "POST" and request.POST.get("ai_generate") == "1":
        title = request.POST.get("title", "")
        company_name = request.POST.get("company_name", "")
        location = request.POST.get("location", "")
        experience_required = request.POST.get("experience_required", "FRESHER_0_1")
        salary_range = request.POST.get("salary_range", "INR_3_6_6")
        urgency_choice = request.POST.get("urgency", "3_DAYS")
        custom_days_raw = request.POST.get("custom_urgency_days", "")

        exp_map = dict(JobDescription.EXPERIENCE_CHOICES)
        sal_map = dict(JobDescription.INR_SALARY_CHOICES)
        _, _, urgency_label, _ = _resolve_urgency_timeline(urgency_choice, custom_days_raw)

        details_text = _generate_ai_job_details(
            title=title,
            company_name=company_name,
            location=location,
            experience_label=exp_map.get(experience_required, experience_required),
            salary_label=sal_map.get(salary_range, salary_range),
            urgency_label=urgency_label,
        )
        return JsonResponse({"ok": True, "details": details_text})

    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        company_name = request.POST.get("company_name", "").strip()
        location = request.POST.get("location", "").strip()
        details = request.POST.get("details", "").strip()
        selected_urgency_choice = request.POST.get("urgency", "3_DAYS")
        selected_custom_days = request.POST.get("custom_urgency_days", "").strip()
        experience_required = request.POST.get("experience_required", "FRESHER_0_1")
        salary_range = request.POST.get("salary_range", "INR_3_6_6")

        try:
            positions_needed = max(1, int(request.POST.get("positions_needed", 1)))
        except (TypeError, ValueError):
            positions_needed = 1

        valid_exps = {k for k, _ in JobDescription.EXPERIENCE_CHOICES}
        valid_sals = {k for k, _ in JobDescription.INR_SALARY_CHOICES}
        _, _, urgency_label, mapped_urgency = _resolve_urgency_timeline(
            selected_urgency_choice, selected_custom_days
        )

        if not title:
            messages.error(request, "Please enter a Job Title.")
        else:
            timeline_line = f"Timeline / Urgency: {urgency_label}"
            final_details = details
            if timeline_line not in final_details:
                final_details = (
                    f"{timeline_line}\n\n{final_details}".strip()
                    if final_details
                    else timeline_line
                )

            job = JobDescription.objects.create(
                title=title,
                company_name=company_name,
                location=location,
                details=final_details,
                positions_needed=positions_needed,
                experience_required=experience_required if experience_required in valid_exps else "FRESHER_0_1",
                salary_range=salary_range if salary_range in valid_sals else "INR_3_6_6",
                urgency=mapped_urgency,
                is_active=True,
            )
            messages.success(
                request,
                f"Job requisition '{job.title}' ({urgency_label}) created and added to Admin Dashboard.",
            )
            return redirect("job_requisition")

    context = {
        "experience_choices": JobDescription.EXPERIENCE_CHOICES,
        "salary_choices": JobDescription.INR_SALARY_CHOICES,
        "urgency_choices": DAY_URGENCY_CHOICES,
        "selected_urgency_choice": selected_urgency_choice,
        "selected_custom_days": selected_custom_days,
    }
    return render(request, "portal_core/job_requisition.html", context)