from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import OfficerProfile, User

# DEVELOPMENT-ONLY credentials. Change or delete these accounts before any real deployment.
DEFAULTS = [
    {
        "username": "citizen1", "password": "Citizen@2026", "role": User.Role.CITIZEN,
        "first_name": "Default", "last_name": "Citizen", "email": "citizen1@example.com",
    },
    {
        "username": "officer1", "password": "Officer@2026", "role": User.Role.OFFICER,
        "first_name": "Default", "last_name": "Officer", "email": "officer1@example.com",
        "department": "General",
    },
    {
        "username": "sysadmin", "password": "SysAdmin@2026", "role": User.Role.ADMIN,
        "first_name": "Default", "last_name": "Admin", "email": "sysadmin@example.com",
    },
]


class Command(BaseCommand):
    help = "Create default dev accounts (citizen1, officer1, sysadmin). Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow running when DEBUG is off.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to create default credentials with DEBUG off (use --force).")

        for spec in DEFAULTS:
            spec = dict(spec)
            password = spec.pop("password")
            department = spec.pop("department", None)
            username = spec.pop("username")
            user, created = User.objects.get_or_create(username=username, defaults=spec)
            if created:
                user.set_password(password)
                if user.role == User.Role.ADMIN:
                    # Seeded sysadmin may also use the Django admin site.
                    user.is_staff = True
                    user.is_superuser = True
                user.save()
            if user.role == User.Role.OFFICER:
                OfficerProfile.objects.get_or_create(
                    user=user, defaults={"department": department or "General"}
                )
            self.stdout.write(f"{'created' if created else 'exists '}  {user.role:8} {username}")
