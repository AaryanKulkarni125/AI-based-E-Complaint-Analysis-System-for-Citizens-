"""Upload validation (REQ-CMP-002/003, REQ-SAFE-002).

A file is accepted only if its extension, and its leading "magic bytes", both say
JPEG / PNG / PDF and agree with each other; size is capped.
"""

from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError

# extension -> (content type, magic-byte prefix)
ALLOWED = {
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".pdf": ("application/pdf", b"%PDF-"),
}


def validate_attachment(uploaded):
    """Raise ValidationError unless ``uploaded`` is an allowed file. Returns its content type."""
    name = PurePath(uploaded.name).name
    ext = PurePath(name).suffix.lower()
    if ext not in ALLOWED:
        raise ValidationError(f"'{name}': only JPEG, PNG or PDF files are allowed.")
    if uploaded.size > settings.MAX_ATTACHMENT_BYTES:
        limit_mb = settings.MAX_ATTACHMENT_BYTES // (1024 * 1024)
        raise ValidationError(f"'{name}' is larger than {limit_mb} MB.")
    if uploaded.size == 0:
        raise ValidationError(f"'{name}' is empty.")

    content_type, magic = ALLOWED[ext]
    head = uploaded.read(len(magic))
    uploaded.seek(0)
    if head != magic:
        raise ValidationError(f"'{name}' does not look like a valid {ext.lstrip('.').upper()} file.")
    return content_type
