from django import forms
from .models import Candidate, JobAssignment, JobDescription


class CandidateSubmissionForm(forms.ModelForm):
    class Meta:
        model = Candidate
        fields = ["job", "full_name", "email", "phone", "notes", "resume"]
        widgets = {
            "job": forms.Select(attrs={"class": "form-select"}),
            "full_name": forms.TextInput(attrs={"class": "form-control", "placeholder": "Candidate full name"}),
            "email": forms.EmailInput(attrs={"class": "form-control", "placeholder": "candidate@example.com"}),
            "phone": forms.TextInput(attrs={"class": "form-control", "placeholder": "+91 98765 43210"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Skills, experience, or notes"}),
            "resume": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, subvendor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.subvendor = subvendor
        if subvendor is not None:
            assigned_job_ids = JobAssignment.objects.filter(assigned_to=subvendor).values_list("job_id", flat=True)
            self.fields["job"].queryset = JobDescription.objects.filter(pk__in=assigned_job_ids).order_by("title")
        self.fields["job"].required = True
        self.fields["full_name"].required = True

    def clean_job(self):
        job = self.cleaned_data["job"]
        if self.subvendor is not None:
            assignment = JobAssignment.objects.filter(assigned_to=self.subvendor, job=job).first()
            if not assignment:
                raise forms.ValidationError("You can only submit profiles for requirements assigned to you.")
            requested = assignment.profiles_requested or 0
            already_sent = Candidate.objects.filter(job=job, submitted_by=self.subvendor).count()
            if requested > 0 and already_sent >= requested:
                raise forms.ValidationError(
                    f"Quota reached for {job.title} ({already_sent}/{requested} profiles already submitted)."
                )
        return job
