from django import forms
from django.conf import settings

from accounts.models import User

from .models import Category, Complaint, Feedback
from .validators import validate_attachment

MIN_DESCRIPTION = 20      # REQ-CMP-001
MIN_REMARKS = 10          # REQ-RES-001

WARD_CHOICES = [
    ("", "-- Select Ward --"),
    ("Ward 1", "Ward 1 - North Zone"),
    ("Ward 2", "Ward 2 - South Zone"),
    ("Ward 3", "Ward 3 - East Zone"),
    ("Ward 4", "Ward 4 - West Zone"),
    ("Ward 5", "Ward 5 - Central Zone"),
    ("Ward 6", "Ward 6 - Industrial Area"),
    ("Ward 7", "Ward 7 - Suburbs"),
]


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    """File field accepting several uploads (pattern from the Django docs)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            cleaned = [single(d, initial) for d in data]
        else:
            cleaned = [single(data, initial)]
        return [f for f in cleaned if f]


def clean_attachment_list(files, max_files):
    if len(files) > max_files:
        raise forms.ValidationError(f"You can attach at most {max_files} files.")
    for f in files:
        validate_attachment(f)
    return files


class ComplaintForm(forms.ModelForm):
    ward = forms.ChoiceField(
        choices=WARD_CHOICES,
        required=False,
        initial="Ward 1",
        help_text="Municipal administrative ward for routing (REQ-GRV-1).",
    )
    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        required=False,
        empty_label="-- Auto-Detect with AI (Recommended) --",
        help_text="Leave blank to let AI automatically classify your complaint.",
    )
    latitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6,
    )
    longitude = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6,
    )
    attachments = MultipleFileField(
        required=False,
        help_text="Optional. Up to 3 files (JPEG, PNG or PDF), 5 MB each.",
    )

    class Meta:
        model = Complaint
        fields = ["category", "ward", "location", "description"]
        widgets = {
            "location": forms.TextInput(attrs={"placeholder": "Street, area or landmark"}),
            "description": forms.Textarea(attrs={"rows": 6, "placeholder": "Describe the problem in detail"}),
        }
        help_texts = {
            "location": "Where is the problem?",
            "description": f"At least {MIN_DESCRIPTION} characters.",
        }

    def clean_description(self):
        text = self.cleaned_data["description"].strip()
        if len(text) < MIN_DESCRIPTION:
            raise forms.ValidationError(
                f"Please describe the problem in at least {MIN_DESCRIPTION} characters "
                f"(currently {len(text)})."
            )
        return text

    def clean_location(self):
        text = self.cleaned_data["location"].strip()
        if not text:
            raise forms.ValidationError("This field is required.")
        return text

    def clean_ward(self):
        ward = self.cleaned_data.get("ward")
        return ward or "Ward 1"

    def clean_attachments(self):
        return clean_attachment_list(
            self.cleaned_data["attachments"], settings.MAX_ATTACHMENTS_PER_COMPLAINT
        )


class OfficerUpdateForm(forms.Form):
    """Officer's status-update form. Only the next legal statuses are offered (REQ-WFL-003)."""

    status = forms.ChoiceField(label="New status")
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text=f"Required when resolving (at least {MIN_REMARKS} characters); optional otherwise.",
    )
    evidence = MultipleFileField(
        required=False,
        label="Resolution evidence",
        help_text="Optional, only used when resolving. Up to 3 files (JPEG, PNG or PDF), 5 MB each.",
    )

    def __init__(self, complaint, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [
            (s.value, s.label) for s in complaint.next_officer_statuses
        ]

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("status")
        remarks = (cleaned.get("remarks") or "").strip()
        cleaned["remarks"] = remarks
        if status == Complaint.Status.RESOLVED and len(remarks) < MIN_REMARKS:
            self.add_error(
                "remarks",
                f"Resolution remarks of at least {MIN_REMARKS} characters are required "
                f"(currently {len(remarks)}).",
            )
        return cleaned

    def clean_evidence(self):
        return clean_attachment_list(
            self.cleaned_data["evidence"], settings.MAX_ATTACHMENTS_PER_COMPLAINT
        )


class AdminReassignForm(forms.Form):
    """Admin manual reassignment form (REQ-ASGN-2)."""

    officer = forms.ModelChoiceField(
        queryset=User.objects.filter(role=User.Role.OFFICER, is_active=True).select_related("officer_profile"),
        label="Select Officer",
        empty_label="-- Choose Active Officer --",
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Reason for reassignment (mandatory)"}),
        label="Reassignment Reason",
        help_text="Mandatory audit trail reason for reassigning this complaint.",
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("A reason for reassignment is mandatory.")
        return reason


class AdminAIOverrideForm(forms.Form):
    """Admin override of AI category and priority (REQ-AI-004/005)."""

    category = forms.ModelChoiceField(
        queryset=Category.objects.all(),
        label="Override Category",
    )
    priority = forms.ChoiceField(
        choices=Complaint.Priority.choices,
        label="Override Priority",
    )
    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Reason for override (e.g. incorrect model prediction)"}),
        required=False,
        label="Override Reason",
    )


class AdminCloseForm(forms.Form):
    """Admin formal closure of a resolved complaint (REQ-RES-004)."""

    remarks = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Closure remarks or administrative sign-off"}),
        required=False,
        label="Closure Remarks",
    )


class CitizenFeedbackForm(forms.Form):
    """Citizen rating and feedback upon resolution (REQ-FDBK-1)."""

    rating = forms.ChoiceField(
        choices=[(5, "5 - Excellent"), (4, "4 - Good"), (3, "3 - Satisfactory"), (2, "2 - Poor"), (1, "1 - Very Poor")],
        label="Satisfaction Rating",
        initial=5,
    )
    comments = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 3, "placeholder": "Share your thoughts on the resolution..."}),
        required=False,
        label="Comments / Feedback",
    )


class CitizenReopenForm(forms.Form):
    """Citizen reopening request for unresolved grievance (REQ-FDBK-2)."""

    reason = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 4, "placeholder": "Explain why the issue is still unresolved..."}),
        label="Reason for Reopening",
        min_length=10,
        help_text="At least 10 characters explaining why the complaint is not resolved.",
    )
