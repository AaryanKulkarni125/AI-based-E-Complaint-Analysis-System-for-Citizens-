import shutil
import tempfile

from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import OfficerProfile, User

from .models import Attachment, Complaint

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GOOD_TEXT = "There is a large pothole near the market that damages vehicles."

TEMP_MEDIA = tempfile.mkdtemp(prefix="ecomplaint-test-media-")


def make_user(username, role, **extra):
    user = User.objects.create_user(
        username, f"{username}@example.com", "Passw0rd!xyz", role=role, first_name=username.title(), **extra
    )
    if role == User.Role.OFFICER:
        OfficerProfile.objects.create(user=user, department="General")
    return user


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ComplaintTestBase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEMP_MEDIA, ignore_errors=True)

    def setUp(self):
        self.citizen = make_user("alice", User.Role.CITIZEN)
        self.other = make_user("bob", User.Role.CITIZEN)
        self.officer = make_user("olga", User.Role.OFFICER)

    def login(self, user):
        self.client.force_login(user)

    def submit(self, text=GOOD_TEXT, location="Market Road", files=()):
        data = {"description": text, "location": location}
        if files:
            data["attachments"] = list(files)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(reverse("complaints:submit"), data)


class SubmitComplaintTests(ComplaintTestBase):
    def test_submission_creates_complaint_routes_to_officer_and_confirms_id(self):
        self.login(self.citizen)
        response = self.submit()
        complaint = Complaint.objects.get()
        self.assertRedirects(response, reverse("complaints:detail", args=[complaint.pk]))
        self.assertEqual(complaint.citizen, self.citizen)
        self.assertEqual(complaint.assigned_officer, self.officer)
        self.assertEqual(complaint.status, Complaint.Status.ASSIGNED)
        self.assertEqual(complaint.reference, f"CMP-{complaint.pk:06d}")
        self.assertEqual(
            [h.to_status for h in complaint.history.all()], ["submitted", "assigned"]
        )
        self.assertContains(self.client.get(response.url), complaint.reference)

    def test_emails_sent_to_citizen_and_officer(self):
        self.login(self.citizen)
        self.submit()
        recipients = sorted(m.to[0] for m in mail.outbox)
        self.assertEqual(recipients, ["alice@example.com", "olga@example.com"])

    def test_short_description_rejected(self):
        self.login(self.citizen)
        response = self.submit(text="too short")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at least 20 characters")
        self.assertFalse(Complaint.objects.exists())

    def test_missing_location_rejected(self):
        self.login(self.citizen)
        self.assertEqual(self.submit(location="   ").status_code, 200)
        self.assertFalse(Complaint.objects.exists())

    def test_queued_when_no_officer_then_assigned_when_one_becomes_active(self):
        OfficerProfile.objects.update(availability_status="inactive")
        self.login(self.citizen)
        self.submit()
        complaint = Complaint.objects.get()
        self.assertEqual(complaint.status, Complaint.Status.SUBMITTED)
        self.assertIsNone(complaint.assigned_officer)
        with self.captureOnCommitCallbacks(execute=True):
            OfficerProfile.objects.filter(user=self.officer).first().save()  # still inactive -> no change
        complaint.refresh_from_db()
        self.assertEqual(complaint.status, Complaint.Status.SUBMITTED)
        profile = OfficerProfile.objects.get(user=self.officer)
        profile.availability_status = "active"
        with self.captureOnCommitCallbacks(execute=True):
            profile.save()
        complaint.refresh_from_db()
        self.assertEqual(complaint.assigned_officer, self.officer)
        self.assertEqual(complaint.status, Complaint.Status.ASSIGNED)

    def test_routing_prefers_least_loaded_active_officer(self):
        busy_free = make_user("pam", User.Role.OFFICER)
        self.login(self.citizen)
        self.submit()   # first goes to olga (lower id, both empty)
        self.submit()   # olga now has 1 open -> goes to pam
        assigned = list(Complaint.objects.order_by("id").values_list("assigned_officer__username", flat=True))
        self.assertEqual(assigned, ["olga", "pam"])
        self.assertEqual(busy_free.officer_profile.workload, 1)

    def test_inactive_officer_is_skipped(self):
        OfficerProfile.objects.filter(user=self.officer).update(availability_status="inactive")
        pam = make_user("pam", User.Role.OFFICER)
        self.login(self.citizen)
        self.submit()
        self.assertEqual(Complaint.objects.get().assigned_officer, pam)

    def test_only_citizens_can_submit(self):
        for user in (self.officer, make_user("root", User.Role.ADMIN)):
            self.login(user)
            self.assertEqual(self.client.get(reverse("complaints:submit")).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("complaints:submit")).status_code, 302)


class AttachmentTests(ComplaintTestBase):
    def test_valid_attachments_are_stored(self):
        self.login(self.citizen)
        self.submit(
            files=[
                SimpleUploadedFile("pothole.png", PNG, "image/png"),
                SimpleUploadedFile("report.pdf", PDF, "application/pdf"),
                SimpleUploadedFile("photo.JPG", JPG, "image/jpeg"),
            ]
        )
        complaint = Complaint.objects.get()
        types = sorted(a.content_type for a in complaint.attachments.all())
        self.assertEqual(types, ["application/pdf", "image/jpeg", "image/png"])
        # Stored under a random name, not the user-supplied one.
        self.assertTrue(all("pothole" not in a.file.name for a in complaint.attachments.all()))

    def assert_rejected(self, files, message):
        self.login(self.citizen)
        response = self.submit(files=files)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, message)
        self.assertFalse(Complaint.objects.exists())
        self.assertFalse(Attachment.objects.exists())

    def test_disallowed_extension(self):
        self.assert_rejected([SimpleUploadedFile("run.exe", b"MZ" + b"0" * 64)], "only JPEG, PNG or PDF")

    def test_extension_and_content_must_match(self):
        self.assert_rejected([SimpleUploadedFile("fake.png", PDF)], "does not look like a valid PNG")
        self.assert_rejected([SimpleUploadedFile("evil.pdf", b"<script>alert(1)</script>")], "valid PDF")

    def test_too_many_files(self):
        files = [SimpleUploadedFile(f"f{i}.png", PNG) for i in range(4)]
        self.assert_rejected(files, "at most 3 files")

    @override_settings(MAX_ATTACHMENT_BYTES=100)
    def test_file_too_large(self):
        self.assert_rejected([SimpleUploadedFile("big.png", PNG + b"0" * 200)], "larger than")

    def test_download_access_control(self):
        self.login(self.citizen)
        self.submit(files=[SimpleUploadedFile("pothole.png", PNG, "image/png")])
        attachment = Attachment.objects.get()
        url = reverse("complaints:attachment", args=[attachment.pk])

        response = self.client.get(url)  # owner
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), PNG)
        self.assertIn("attachment", response["Content-Disposition"])

        self.login(self.officer)  # assigned officer
        self.assertEqual(self.client.get(url).status_code, 200)

        self.login(self.other)  # someone else's complaint
        self.assertEqual(self.client.get(url).status_code, 404)
        self.login(make_user("pam", User.Role.OFFICER))  # not the assigned officer
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)


class TrackingTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.citizen)
        self.submit()
        self.submit(text="Streetlight outside house 12 has not worked for a week.", location="Lake View")
        self.mine = list(Complaint.objects.filter(citizen=self.citizen).order_by("id"))
        self.client.logout()
        self.login(self.other)
        self.submit(text="Garbage has not been collected from our lane for days.", location="Lane 4")
        self.theirs = Complaint.objects.get(citizen=self.other)
        self.login(self.citizen)

    def test_list_shows_only_own_complaints(self):
        response = self.client.get(reverse("complaints:my_list"))
        self.assertEqual(set(response.context["complaints"]), set(self.mine))

    def test_other_users_complaint_detail_is_404(self):
        self.assertEqual(self.client.get(reverse("complaints:detail", args=[self.theirs.pk])).status_code, 404)

    def test_search_by_tracking_id_and_status_filter(self):
        url = reverse("complaints:my_list")
        found = self.client.get(url, {"q": self.mine[0].reference.lower()}).context["complaints"]
        self.assertEqual(list(found), [self.mine[0]])
        # another citizen's ID finds nothing
        self.assertContains(self.client.get(url, {"q": self.theirs.reference}), "No matching complaint found")
        self.assertEqual(self.client.get(url, {"status": "assigned"}).context["complaints"].count(), 2)
        self.assertEqual(self.client.get(url, {"status": "resolved"}).context["complaints"].count(), 0)

    def test_citizen_cannot_open_officer_list_and_officer_cannot_open_citizen_list(self):
        self.assertEqual(self.client.get(reverse("complaints:my_list")).status_code, 200)
        self.login(self.officer)
        self.assertEqual(self.client.get(reverse("complaints:my_list")).status_code, 403)

    def test_dashboards_show_counts(self):
        self.assertContains(self.client.get(reverse("accounts:dashboard")), "Open complaints")
        self.login(self.officer)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.context["workload"], 3)

    def test_complaints_cannot_be_deleted_through_admin(self):
        from .admin import ComplaintAdmin
        from django.contrib import admin as dj_admin

        self.assertFalse(ComplaintAdmin(Complaint, dj_admin.site).has_delete_permission(None))


class OfficerUpdateTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.citizen)
        self.submit()
        self.complaint = Complaint.objects.get()
        mail.outbox.clear()
        self.login(self.officer)
        self.url = reverse("complaints:detail", args=[self.complaint.pk])

    def update(self, status, remarks="", files=()):
        data = {"status": status, "remarks": remarks}
        if files:
            data["evidence"] = list(files)
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post(self.url, data)

    def reload(self):
        self.complaint.refresh_from_db()
        return self.complaint

    def test_officer_list_shows_assigned_complaint_and_counts(self):
        response = self.client.get(reverse("complaints:officer_list"))
        self.assertEqual(list(response.context["complaints"]), [self.complaint])
        self.assertEqual(response.context["counts"], {"pending": 1, "resolved": 0})

    def test_officer_list_excludes_other_officers_complaints_and_sorts(self):
        pam = make_user("pam", User.Role.OFFICER)
        Complaint.objects.create(citizen=self.citizen, description="x" * 30, location="L",
                                 assigned_officer=pam, status="assigned")
        low = Complaint.objects.create(citizen=self.citizen, description="y" * 30, location="L",
                                       assigned_officer=self.officer, status="assigned", priority="low")
        high = Complaint.objects.create(citizen=self.citizen, description="z" * 30, location="L",
                                        assigned_officer=self.officer, status="assigned", priority="high")
        by_priority = list(self.client.get(reverse("complaints:officer_list")).context["complaints"])
        self.assertEqual(by_priority, [high, self.complaint, low])
        by_date = list(self.client.get(reverse("complaints:officer_list"), {"sort": "date"}).context["complaints"])
        self.assertEqual(by_date, [high, low, self.complaint])
        filtered = self.client.get(reverse("complaints:officer_list"), {"status": "resolved"})
        self.assertEqual(filtered.context["complaints"].count(), 0)

    def test_full_workflow_acknowledge_progress_resolve(self):
        self.assertRedirects(self.update("acknowledged"), self.url)
        self.assertEqual(self.reload().status, "acknowledged")
        self.update("in_progress", "Crew scheduled for Thursday.")
        self.assertEqual(self.reload().status, "in_progress")
        self.update("resolved", "Pothole filled and surface levelled.")
        c = self.reload()
        self.assertEqual(c.status, "resolved")
        self.assertEqual(c.resolved_by, self.officer)
        self.assertEqual(c.resolution_remarks, "Pothole filled and surface levelled.")
        self.assertIsNotNone(c.resolved_at)
        self.assertEqual(c.resolution_time, c.resolved_at - c.submitted_at)
        self.assertEqual(
            [h.to_status for h in c.history.all()],
            ["submitted", "assigned", "acknowledged", "in_progress", "resolved"],
        )
        # No further officer action once resolved.
        self.assertEqual(self.client.post(self.url, {"status": "closed"}).status_code, 405)
        self.assertEqual(self.reload().status, "resolved")

    def test_citizen_emailed_on_every_status_change(self):
        self.update("acknowledged")
        self.update("in_progress")
        self.update("resolved", "All done, verified on site.")
        self.assertEqual([m.to for m in mail.outbox], [["alice@example.com"]] * 3)
        self.assertIn("Resolved", mail.outbox[-1].subject)
        self.assertIn("All done, verified on site.", mail.outbox[-1].body)

    def test_statuses_cannot_be_skipped(self):
        for bad in ("in_progress", "resolved", "closed", "submitted", "assigned"):
            response = self.update(bad, "remarks long enough here")
            self.assertEqual(response.status_code, 200, bad)  # form re-rendered with an error
            self.assertEqual(self.reload().status, "assigned", bad)

    def test_resolving_requires_remarks_of_ten_characters(self):
        self.update("acknowledged")
        self.update("in_progress")
        for remarks in ("", "   ", "too short"):
            response = self.update("resolved", remarks)
            self.assertContains(response, "at least 10 characters")
            self.assertEqual(self.reload().status, "in_progress")

    def test_evidence_attached_when_resolving(self):
        self.update("acknowledged")
        self.update("in_progress")
        self.update("resolved", "Repair completed today.", files=[SimpleUploadedFile("after.jpg", JPG, "image/jpeg")])
        evidence = Attachment.objects.get(is_resolution_evidence=True)
        self.assertEqual(evidence.complaint, self.complaint)
        # the citizen can see (and download) the evidence
        self.login(self.citizen)
        self.assertContains(self.client.get(self.url), "resolution evidence")
        self.assertEqual(self.client.get(reverse("complaints:attachment", args=[evidence.pk])).status_code, 200)

    def test_bad_evidence_blocks_the_resolution(self):
        self.update("acknowledged")
        self.update("in_progress")
        response = self.update("resolved", "Repair completed today.", files=[SimpleUploadedFile("x.exe", b"MZ" + b"0" * 50)])
        self.assertContains(response, "only JPEG, PNG or PDF")
        self.assertEqual(self.reload().status, "in_progress")

    def test_only_assigned_officer_can_update(self):
        self.login(make_user("pam", User.Role.OFFICER))
        self.assertEqual(self.client.post(self.url, {"status": "acknowledged"}).status_code, 404)
        self.assertEqual(self.reload().status, "assigned")

    def test_citizens_cannot_update_status(self):
        self.login(self.citizen)
        self.assertEqual(self.client.post(self.url, {"status": "acknowledged"}).status_code, 405)
        self.assertEqual(self.reload().status, "assigned")

    def test_service_rejects_wrong_officer_directly(self):
        from . import services

        pam = make_user("pam", User.Role.OFFICER)
        with self.assertRaises(services.WorkflowError):
            services.change_status(self.complaint, pam, "acknowledged")

    def test_stale_second_update_is_rejected(self):
        from . import services

        self.update("acknowledged")
        with self.assertRaises(services.WorkflowError):
            services.change_status(self.complaint, self.officer, "acknowledged")  # already acknowledged

    def test_officer_dashboard_workload_drops_after_resolution(self):
        self.update("acknowledged")
        self.update("in_progress")
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).context["workload"], 1)
        self.update("resolved", "Resolved with remarks.")
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual((response.context["workload"], response.context["resolved_count"]), (0, 1))


class AICategorizationTests(TestCase):
    def test_ai_categorizes_pothole_as_roads(self):
        from complaints.ai import classify_text
        cat, prio, conf, needs_rev = classify_text("Severe deep pothole on arterial road damaging cars and causing accidents")
        self.assertEqual(cat, "Roads & Infrastructure")
        self.assertEqual(prio, "high")
        self.assertGreater(conf, 0.0)

    def test_ai_categorizes_sparking_as_electricity(self):
        from complaints.ai import classify_text
        cat, prio, conf, _ = classify_text("Transformer sparking with fire and black smoke near school")
        self.assertEqual(cat, "Electricity & Street Lighting")
        self.assertEqual(prio, "high")

    def test_ai_categorizes_garbage_as_sanitation(self):
        from complaints.ai import classify_text
        cat, prio, conf, _ = classify_text("Huge garbage dump overflowing on street corner with foul smell")
        self.assertEqual(cat, "Sanitation & Waste Management")
        self.assertEqual(prio, "medium")

    def test_ai_fallback_on_unclassifiable_text(self):
        from complaints.ai import classify_text
        cat, prio, conf, needs_rev = classify_text("xyz random gibberish 123456789")
        # should not crash; flags review if confidence is low
        self.assertTrue(needs_rev)


class DuplicateDetectionTests(ComplaintTestBase):
    def test_duplicate_flagged_for_similar_complaint_in_same_ward(self):
        self.login(self.citizen)
        c1 = self.submit("Broken water pipeline leaking clean drinking water on main road", location="North Street")
        self.login(self.other)
        # Second citizen reports same issue in same ward
        self.submit("Broken water pipeline leaking clean drinking water on main road", location="North Street")
        from complaints.models import Complaint
        c2 = Complaint.objects.order_by("-id").first()
        self.assertTrue(c2.is_duplicate)
        self.assertEqual(c2.duplicate_of.pk, 1)


class AdminWorkflowTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("adminuser", User.Role.ADMIN)
        self.second_officer = make_user("sam", User.Role.OFFICER)
        self.login(self.citizen)
        self.submit()
        self.complaint = Complaint.objects.get()

    def test_admin_manual_reassignment_with_audit_log(self):
        from complaints import services
        from complaints.models import AssignmentLog

        services.admin_reassign_complaint(
            self.complaint, self.second_officer, self.admin, "Officer Olga is on leave."
        )
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.assigned_officer, self.second_officer)
        log = AssignmentLog.objects.filter(complaint=self.complaint).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.from_officer, self.officer)
        self.assertEqual(log.to_officer, self.second_officer)
        self.assertEqual(log.assigned_by, self.admin)
        self.assertEqual(log.reason, "Officer Olga is on leave.")

    def test_reassignment_without_reason_rejected(self):
        from complaints import services
        with self.assertRaises(services.WorkflowError):
            services.admin_reassign_complaint(self.complaint, self.second_officer, self.admin, "")

    def test_admin_ai_override_with_audit_log(self):
        from complaints import services
        from complaints.models import AIOverrideLog, Category

        new_cat = Category.objects.create(name="Sanitation Extra", department_name="Sanitation")
        services.admin_override_ai(self.complaint, new_cat, "high", self.admin, "Correction by triage.")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.category, new_cat)
        self.assertEqual(self.complaint.priority, "high")
        self.assertFalse(self.complaint.needs_review)

        log = AIOverrideLog.objects.filter(complaint=self.complaint).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.corrected_category, new_cat)
        self.assertEqual(log.corrected_priority, "high")
        self.assertEqual(log.actor, self.admin)

    def test_admin_close_resolved_complaint(self):
        from complaints import services

        # Move to resolved
        services.change_status(self.complaint, self.officer, "acknowledged")
        services.change_status(self.complaint, self.officer, "in_progress")
        services.change_status(self.complaint, self.officer, "resolved", remarks="All repaired properly.")

        services.admin_close_complaint(self.complaint, self.admin, "Verified by ward inspector.")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Complaint.Status.CLOSED)
        self.assertEqual(self.complaint.closed_by, self.admin)

    def test_cannot_close_unresolved_complaint(self):
        from complaints import services
        with self.assertRaises(services.WorkflowError):
            services.admin_close_complaint(self.complaint, self.admin, "Cannot close yet.")


class CitizenFeedbackAndReopenTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.login(self.citizen)
        self.submit()
        self.complaint = Complaint.objects.get()
        from complaints import services
        services.change_status(self.complaint, self.officer, "acknowledged")
        services.change_status(self.complaint, self.officer, "in_progress")
        services.change_status(self.complaint, self.officer, "resolved", remarks="Issue fixed permanently.")
        self.complaint.refresh_from_db()

    def test_citizen_submits_feedback_rating(self):
        from complaints import services
        from complaints.models import Feedback

        fb = services.submit_citizen_feedback(self.complaint, self.citizen, 5, "Prompt and excellent work!")
        self.assertEqual(fb.rating, 5)
        self.assertEqual(fb.comments, "Prompt and excellent work!")
        self.assertTrue(Feedback.objects.filter(complaint=self.complaint).exists())

    def test_other_citizen_cannot_submit_feedback(self):
        from complaints import services
        with self.assertRaises(services.WorkflowError):
            services.submit_citizen_feedback(self.complaint, self.other, 4, "Not my complaint.")

    def test_citizen_reopens_complaint(self):
        from complaints import services

        services.reopen_complaint(self.complaint, self.citizen, "Water is still leaking this morning.")
        self.complaint.refresh_from_db()
        self.assertEqual(self.complaint.status, Complaint.Status.REOPENED)
        self.assertTrue(
            self.complaint.history.filter(to_status=Complaint.Status.REOPENED).exists()
        )


class NotificationLogAndRetryTests(TestCase):
    def test_notification_logging_and_retry(self):
        from complaints.notifications import _send, retry_failed_notifications
        from complaints.models import NotificationLog

        log = _send("user@example.com", "Test Subject", "Test Body")
        self.assertIsNotNone(log)
        self.assertEqual(log.status, "sent")
        self.assertEqual(log.recipient, "user@example.com")

        # Test retry mechanism
        failed_entry = NotificationLog.objects.create(
            recipient="retry@example.com",
            subject="Retry Test",
            message="Retry Body",
            status="failed",
            retry_count=0,
        )
        count = retry_failed_notifications()
        self.assertGreaterEqual(count, 1)
        failed_entry.refresh_from_db()
        self.assertEqual(failed_entry.status, "sent")


class AdminViewsAndExportTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("superadmin", User.Role.ADMIN)
        self.login(self.citizen)
        self.submit()

    def test_admin_complaint_list_view(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:admin_complaint_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CMP-000001")

    def test_admin_map_view(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:admin_map_view"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "map")

    def test_admin_analytics_view(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:admin_analytics"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Analytics & Reporting")

    def test_export_csv(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:export_csv"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(b"Reference,Citizen", response.content)

    def test_export_pdf(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:export_pdf"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_officer_roster_and_status_toggle(self):
        self.login(self.admin)
        response = self.client.get(reverse("complaints:admin_officer_roster"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.officer.username)

        # Toggle officer status
        toggle_url = reverse("complaints:admin_toggle_officer_status", args=[self.officer.pk])
        self.client.post(toggle_url)
        self.officer.officer_profile.refresh_from_db()
        self.assertEqual(self.officer.officer_profile.availability_status, "inactive")


class RestApiTests(ComplaintTestBase):
    def setUp(self):
        super().setUp()
        self.admin = make_user("adminapi", User.Role.ADMIN)
        self.login(self.citizen)
        self.submit()
        self.complaint = Complaint.objects.get()

    def test_get_complaints_collection_api(self):
        self.login(self.citizen)
        response = self.client.get("/api/complaints/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["data"]["items"]), 1)
        self.assertEqual(data["data"]["items"][0]["reference"], self.complaint.reference)

    def test_get_complaint_detail_api(self):
        self.login(self.citizen)
        response = self.client.get(f"/api/complaints/{self.complaint.pk}/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"]["reference"], self.complaint.reference)

    def test_analytics_api_forbidden_for_citizen(self):
        self.login(self.citizen)
        response = self.client.get("/api/analytics/")
        self.assertEqual(response.status_code, 403)

    def test_analytics_api_success_for_admin(self):
        self.login(self.admin)
        response = self.client.get("/api/analytics/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data["data"])
        self.assertEqual(data["data"]["summary"]["total"], 1)

    def test_map_data_api(self):
        self.complaint.latitude = 19.0760
        self.complaint.longitude = 72.8777
        self.complaint.save()

        response = self.client.get("/api/map-data/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["data"]), 1)
        self.assertEqual(data["data"][0]["reference"], self.complaint.reference)

    def test_categories_api(self):
        response = self.client.get("/api/categories/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data["data"], list)
