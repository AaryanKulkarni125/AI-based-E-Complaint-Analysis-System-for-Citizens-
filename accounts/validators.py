import re

from django.core.exceptions import ValidationError


class LetterAndDigitValidator:
    """REQ-AUTH-002: passwords must mix alphabetic and numeric characters."""

    def validate(self, password, user=None):
        if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
            raise ValidationError(
                "Password must contain both letters and numbers.",
                code="password_no_letter_digit_mix",
            )

    def get_help_text(self):
        return "Your password must contain both letters and numbers."
