from django import forms
from django.conf import settings

from .models import Complaint
from .validators import validate_attachment

MIN_DESCRIPTION = 20      # REQ-CMP-001
MIN_REMARKS = 10          # REQ-RES-001


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
    attachments = MultipleFileField(
        required=False,
        help_text="Optional. Up to 3 files (JPEG, PNG or PDF), 5 MB each.",
    )

    class Meta:
        model = Complaint
        fields = ["location", "description"]
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
