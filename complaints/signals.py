from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from accounts.models import OfficerProfile

from .services import assign_queued_complaints


@receiver(post_save, sender=OfficerProfile)
def route_waiting_complaints(sender, instance, **kwargs):
    """When an officer registers or becomes active, hand them any complaints that were queued."""
    if instance.availability_status == OfficerProfile.Availability.ACTIVE:
        transaction.on_commit(assign_queued_complaints)
