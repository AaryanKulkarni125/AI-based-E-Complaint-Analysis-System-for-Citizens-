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

        from complaints.models import Category
        categories = [
            ("Roads & Infrastructure", "Roads & Traffic", 48, "Potholes, broken roads, damaged pavements, road cave-ins"),
            ("Sanitation & Waste Management", "Sanitation", 24, "Garbage piles, dead animals, uncollected bins, litter"),
            ("Water Supply", "Water Works", 48, "Burst pipes, contaminated water, low water pressure, no water"),
            ("Drainage & Sewerage", "Drainage", 48, "Sewage overflow, blocked storm drains, missing manhole covers"),
            ("Electricity & Street Lighting", "Electrical", 24, "Broken streetlights, sparking transformers, dangling wires"),
            ("Public Health", "Public Health", 36, "Mosquito breeding, stagnant water, stray dog nuisance"),
            ("General Administration", "Administration", 72, "Administrative delays, civic inquiries, staff issues"),
        ]
        for cat_name, dept_name, sla_h, desc in categories:
            cat, cat_created = Category.objects.get_or_create(
                name=cat_name,
                defaults={"department_name": dept_name, "sla_hours": sla_h, "description": desc},
            )
            if cat_created:
                self.stdout.write(f"created  category {cat_name} (SLA: {sla_h}h)")
