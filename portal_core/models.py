from django.db import models
# Create your models here.
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
class User(AbstractUser):
    ROLE_CHOICES = [
        ("ADMIN", "Admin"),
        ("RECRUITER", "Recruiter"),
        ("SUBVENDOR", "Subvendor"),
    ]
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default="ADMIN")
    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"
class JobDescription(models.Model):
    title = models.CharField(max_length=200)
    location = models.CharField(max_length=120, blank=True)
    details = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    SEVERITY_CHOICES = [("EMERGENCY", "Emergency"), ("HIGH", "High"), ("NORMAL", "Normal")]
    EXPERIENCE_CHOICES = [
        ("FRESHER_0_1", "Fresher (0-1 Yrs)"),
        ("1_2_YRS", "1-2 Yrs"),
        ("2_3_YRS", "2-3 Yrs"),
        ("3_5_YRS", "3-5 Yrs"),
        ("5_8_YRS", "5-8 Yrs"),
        ("8_PLUS_YRS", "8+ Yrs"),
    ]
    INR_SALARY_CHOICES = [
        ("INR_1_8_3_6", "₹1.8L - ₹3.6 LPA"),
        ("INR_3_6_6", "₹3.6L - ₹6 LPA"),
        ("INR_6_10", "₹6L - ₹10 LPA"),
        ("INR_10_15", "₹10L - ₹15 LPA"),
        ("INR_15_25", "₹15L - ₹25 LPA"),
        ("INR_25_PLUS", "₹25+ LPA"),
        ("NEGOTIABLE", "Negotiable (INR)"),
    ]
    URGENCY_CHOICES = [
        ("EMERGENCY", "Emergency"),
        ("HIGH", "High"),
        ("NORMAL", "Normal"),
        ("LOW", "Low"),
    ]

    positions_needed = models.PositiveIntegerField(default=1)
    experience_required = models.CharField(
        max_length=50,
        choices=EXPERIENCE_CHOICES,
        default="FRESHER_0_1",
    )
    salary_range = models.CharField(
        max_length=50,
        choices=INR_SALARY_CHOICES,
        default="INR_3_6_6",
    )
    urgency = models.CharField(
        max_length=20,
        choices=URGENCY_CHOICES,
        default="NORMAL",
    )

    company_name = models.CharField(max_length=150, default="")
    def __str__(self):
        return self.title
    salary = models.CharField(max_length=100, blank=True, default="")

    def save(self, *args, **kwargs):
        label = self.get_salary_range_display()
        if hasattr(self, 'salary') and label:
            self.salary = label
        super().save(*args, **kwargs)

class Candidate(models.Model):
    STATUS_CHOICES = [
        ("SUBMITTED_BY_SUBVENDOR", "Submitted by Subvendor"),
        ("COMPANY_A_REVIEW", "Company A Review"),
        ("SUBMITTED_TO_CLIENT", "Submitted to Client"),
        ("CLIENT_SHORTLISTED", "Client Shortlisted"),
        ("INTERVIEW_STAGE", "Interview Stage"),
        ("OFFER_RELEASED", "Offer Released"),
        ("JOINED_HIRED", "Joined (Hired)"),
    ]
    full_name = models.CharField(max_length=150)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    job = models.ForeignKey(
        JobDescription,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="candidates",
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="submitted_candidates",
    )
    status = models.CharField(
        max_length=40,
        choices=STATUS_CHOICES,
        default="SUBMITTED_BY_SUBVENDOR",
    )
    resume = models.FileField(upload_to="resumes/", blank=True, null=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ["-created_at"]
    def __str__(self):
        return self.full_name
class JobAssignment(models.Model):
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.CASCADE,
        related_name="assignments",
        null=True,
        blank=True,
    )
    job = models.ForeignKey(
        JobDescription,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assignments",
    )
    remarks = models.CharField(max_length=255, blank=True)
    assigned_at = models.DateTimeField(auto_now_add=True)
    profiles_requested = models.PositiveIntegerField(default=1, verbose_name="Profiles Requested")
    def __str__(self):
        return f"{self.candidate} - {self.job}"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="portal_notifications",
    )
    assignment = models.ForeignKey(
        "JobAssignment",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.recipient.username}: {self.message[:60]}"


def _build_assignment_alert_message(instance):
    user_name = getattr(instance.assigned_to, "username", "Subvendor")
    job = instance.job
    profiles_req = getattr(instance, "profiles_requested", 1)
    job_title = getattr(job, "title", "Job")
    company = getattr(job, "company_name", "") or "Client"
    positions = getattr(job, "positions_needed", 1)
    exp_disp = job.get_experience_required_display() if hasattr(job, "get_experience_required_display") else getattr(job, "experience_required", "")
    sal_disp = job.get_salary_range_display() if hasattr(job, "get_salary_range_display") else (getattr(job, "salary_range", "") or getattr(job, "salary", ""))
    urg_disp = job.get_urgency_display() if hasattr(job, "get_urgency_display") else getattr(job, "urgency", "")

    details = [f"Total positions: {positions}"]
    if exp_disp:
        details.append(f"Exp: {exp_disp}")
    if sal_disp:
        details.append(f"Salary: {sal_disp}")
    if urg_disp:
        details.append(f"Urgency: {urg_disp}")
    meta_str = ", ".join(details)

    return (
        f"Hey {user_name}, you received a new requirement: "
        f"need {profiles_req} profiles on {job_title} for {company} ({meta_str})."
    )


from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=JobAssignment)
def create_subvendor_assignment_notification(sender, instance, created, **kwargs):
    if not instance.assigned_to or not instance.job:
        return
    msg = _build_assignment_alert_message(instance)
    if created:
        Notification.objects.create(
            recipient=instance.assigned_to,
            assignment=instance,
            message=msg,
        )
    else:
        latest = Notification.objects.filter(assignment=instance, recipient=instance.assigned_to).first()
        if latest:
            if latest.message != msg:
                latest.message = msg
                latest.is_read = False
                latest.save(update_fields=["message", "is_read"])
        else:
            Notification.objects.create(
                recipient=instance.assigned_to,
                assignment=instance,
                message=msg,
            )
