import csv
from io import BytesIO

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Avg, Case, Count, IntegerField, Q, Value, When
from django.http import FileResponse, Http404, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.decorators import role_required
from accounts.models import OfficerProfile, User

from . import notifications, services
from .forms import (
    AdminAIOverrideForm,
    AdminCloseForm,
    AdminReassignForm,
    CitizenFeedbackForm,
    CitizenReopenForm,
    ComplaintForm,
    OfficerUpdateForm,
)
from .models import Attachment, Category, Complaint, Feedback, NotificationLog


def visible_complaints(user):
    """Citizens see their own, officers see what is assigned to them, admins see all (REQ-ADM-001)."""
    if user.role == User.Role.CITIZEN:
        return Complaint.objects.filter(citizen=user)
    if user.role == User.Role.OFFICER:
        return Complaint.objects.filter(assigned_officer=user)
    if user.role == User.Role.ADMIN:
        return Complaint.objects.all()
    return Complaint.objects.none()


@role_required(User.Role.CITIZEN)
def submit(request):
    form = ComplaintForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        complaint = services.create_complaint(
            citizen=request.user,
            description=form.cleaned_data["description"],
            location=form.cleaned_data["location"],
            files=form.cleaned_data["attachments"],
            ward=form.cleaned_data.get("ward", "Ward 1"),
            latitude=form.cleaned_data.get("latitude"),
            longitude=form.cleaned_data.get("longitude"),
            category=form.cleaned_data.get("category"),
        )
        messages.success(
            request,
            f"Your complaint has been submitted. Your tracking ID is {complaint.reference}.",
        )
        return redirect("complaints:detail", pk=complaint.pk)
    return render(request, "complaints/submit.html", {"form": form})


@role_required(User.Role.CITIZEN)
def confirmation(request, pk):
    """Submission confirmation page with unique tracking ID (REQ-GRV-3)."""
    complaint = get_object_or_404(Complaint.objects.filter(citizen=request.user), pk=pk)
    return render(request, "complaints/confirmation.html", {"complaint": complaint})


@role_required(User.Role.CITIZEN)
def my_list(request):
    complaints = Complaint.objects.filter(citizen=request.user).select_related(
        "assigned_officer", "category"
    )

    status = request.GET.get("status", "")
    if status in Complaint.Status.values:
        complaints = complaints.filter(status=status)
    else:
        status = ""

    query = request.GET.get("q", "").strip()
    if query:
        pk = Complaint.pk_from_reference(query)
        complaints = complaints.filter(
            Q(pk=pk) if pk else Q(description__icontains=query) | Q(location__icontains=query)
        )

    return render(
        request,
        "complaints/my_list.html",
        {
            "complaints": complaints,
            "statuses": Complaint.Status.choices,
            "active_status": status,
            "query": query,
        },
    )


@role_required(User.Role.OFFICER)
def officer_list(request):
    """REQ-OFF-001..004: only my complaints, sortable and filterable, with SLA tracking."""
    mine = Complaint.objects.filter(assigned_officer=request.user).select_related("citizen", "category")
    counts = {
        "pending": mine.exclude(status__in=["resolved", "closed"]).count(),
        "resolved": mine.filter(status__in=["resolved", "closed"]).count(),
    }

    status = request.GET.get("status", "")
    if status in Complaint.Status.values:
        mine = mine.filter(status=status)
    else:
        status = ""

    sort = request.GET.get("sort", "priority")
    if sort == "date":
        mine = mine.order_by("-submitted_at", "-id")
    else:
        sort = "priority"
        rank = Case(
            When(priority=Complaint.Priority.HIGH, then=Value(0)),
            When(priority=Complaint.Priority.MEDIUM, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )
        mine = mine.order_by(rank, "submitted_at", "id")

    return render(
        request,
        "complaints/officer_list.html",
        {
            "complaints": mine,
            "counts": counts,
            "statuses": Complaint.Status.choices,
            "active_status": status,
            "sort": sort,
        },
    )


@role_required(User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN)
def detail(request, pk):
    complaint = get_object_or_404(
        visible_complaints(request.user).select_related(
            "assigned_officer", "resolved_by", "category", "closed_by"
        ),
        pk=pk,
    )

    update_form = None
    reassign_form = None
    override_form = None
    close_form = None
    feedback_form = None
    reopen_form = None

    action = request.POST.get("form_action") if request.method == "POST" else None

    # 1. Officer Status Update
    if request.user.role == User.Role.OFFICER:
        if complaint.next_officer_statuses:
            if request.method == "POST":
                update_form = OfficerUpdateForm(complaint, request.POST, request.FILES)
                if update_form.is_valid():
                    try:
                        services.change_status(
                            complaint,
                            request.user,
                            update_form.cleaned_data["status"],
                            remarks=update_form.cleaned_data["remarks"],
                            evidence=update_form.cleaned_data["evidence"],
                        )
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
                    else:
                        messages.success(
                            request,
                            f"{complaint.reference} updated to \"{Complaint.Status(update_form.cleaned_data['status']).label}\".",
                        )
                    return redirect("complaints:detail", pk=complaint.pk)
            else:
                update_form = OfficerUpdateForm(complaint)
        elif request.method == "POST":
            return HttpResponseNotAllowed(["GET"])

    # 2. Admin Actions (Reassign, Override AI, Close)
    elif request.user.role == User.Role.ADMIN:
        reassign_form = AdminReassignForm(initial={"officer": complaint.assigned_officer})
        override_form = AdminAIOverrideForm(initial={"category": complaint.category, "priority": complaint.priority})
        close_form = AdminCloseForm()

        if request.method == "POST":
            if action == "admin_reassign":
                reassign_form = AdminReassignForm(request.POST)
                if reassign_form.is_valid():
                    try:
                        services.admin_reassign_complaint(
                            complaint,
                            reassign_form.cleaned_data["officer"],
                            request.user,
                            reassign_form.cleaned_data["reason"],
                        )
                        messages.success(request, f"{complaint.reference} reassigned to {reassign_form.cleaned_data['officer'].username}.")
                        return redirect("complaints:detail", pk=complaint.pk)
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
            elif action == "admin_override_ai":
                override_form = AdminAIOverrideForm(request.POST)
                if override_form.is_valid():
                    try:
                        services.admin_override_ai(
                            complaint,
                            override_form.cleaned_data["category"],
                            override_form.cleaned_data["priority"],
                            request.user,
                            override_form.cleaned_data["reason"],
                        )
                        messages.success(request, f"AI predictions overridden for {complaint.reference}.")
                        return redirect("complaints:detail", pk=complaint.pk)
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
            elif action == "admin_close":
                close_form = AdminCloseForm(request.POST)
                if close_form.is_valid():
                    try:
                        services.admin_close_complaint(complaint, request.user, close_form.cleaned_data["remarks"])
                        messages.success(request, f"{complaint.reference} has been formally closed.")
                        return redirect("complaints:detail", pk=complaint.pk)
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
            else:
                return HttpResponseNotAllowed(["GET"])

    # 3. Citizen Feedback & Reopen
    elif request.user.role == User.Role.CITIZEN:
        feedback_obj = getattr(complaint, "feedback", None)
        if complaint.status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
            feedback_form = CitizenFeedbackForm(
                initial={"rating": feedback_obj.rating if feedback_obj else 5, "comments": feedback_obj.comments if feedback_obj else ""}
            )
        if complaint.status == Complaint.Status.RESOLVED and (complaint.can_be_reopened or request.user.is_system_admin):
            reopen_form = CitizenReopenForm()

        if request.method == "POST":
            if action == "citizen_feedback" and complaint.status in (Complaint.Status.RESOLVED, Complaint.Status.CLOSED):
                feedback_form = CitizenFeedbackForm(request.POST)
                if feedback_form.is_valid():
                    try:
                        services.submit_citizen_feedback(
                            complaint,
                            request.user,
                            feedback_form.cleaned_data["rating"],
                            feedback_form.cleaned_data["comments"],
                        )
                        messages.success(request, "Thank you! Your feedback has been recorded.")
                        return redirect("complaints:detail", pk=complaint.pk)
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
            elif action == "reopen" and complaint.status == Complaint.Status.RESOLVED and (complaint.can_be_reopened or request.user.is_system_admin):
                reopen_form = CitizenReopenForm(request.POST)
                if reopen_form.is_valid():
                    try:
                        services.reopen_complaint(complaint, request.user, reopen_form.cleaned_data["reason"])
                        messages.warning(request, f"{complaint.reference} has been reopened and returned to investigation.")
                        return redirect("complaints:detail", pk=complaint.pk)
                    except services.WorkflowError as exc:
                        messages.error(request, str(exc))
            else:
                return HttpResponseNotAllowed(["GET"])

    elif request.method == "POST":
        return HttpResponseNotAllowed(["GET"])

    return render(
        request,
        "complaints/detail.html",
        {
            "complaint": complaint,
            "history": complaint.history.select_related("changed_by"),
            "attachments": complaint.attachments.all(),
            "assignment_logs": complaint.assignment_logs.select_related("from_officer", "to_officer", "assigned_by"),
            "ai_override_logs": complaint.ai_override_logs.select_related("original_category", "corrected_category", "actor"),
            "update_form": update_form,
            "reassign_form": reassign_form,
            "override_form": override_form,
            "close_form": close_form,
            "feedback_form": feedback_form,
            "reopen_form": reopen_form,
            "feedback": getattr(complaint, "feedback", None),
        },
    )


@role_required(User.Role.CITIZEN, User.Role.OFFICER, User.Role.ADMIN)
def download_attachment(request, pk):
    attachment = get_object_or_404(
        Attachment.objects.filter(complaint__in=visible_complaints(request.user)), pk=pk
    )
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404("File is no longer available.")
    return FileResponse(
        handle,
        content_type=attachment.content_type,
        as_attachment=True,
        filename=attachment.original_name,
    )


# --- Administrator Views ---


@role_required(User.Role.ADMIN)
def admin_complaint_list(request):
    """Admin comprehensive management console (REQ-ADM-001)."""
    qs = Complaint.objects.all().select_related("citizen", "assigned_officer", "category")

    # Status filter
    status = request.GET.get("status", "")
    if status in Complaint.Status.values:
        qs = qs.filter(status=status)

    # Category filter
    category_id = request.GET.get("category", "")
    if category_id and category_id.isdigit():
        qs = qs.filter(category_id=int(category_id))

    # Priority filter
    priority = request.GET.get("priority", "")
    if priority in Complaint.Priority.values:
        qs = qs.filter(priority=priority)

    # Ward filter
    ward = request.GET.get("ward", "")
    if ward:
        qs = qs.filter(ward__iexact=ward.strip())

    # Needs review filter
    if request.GET.get("needs_review") == "1":
        qs = qs.filter(needs_review=True)

    # Search query
    query = request.GET.get("q", "").strip()
    if query:
        pk = Complaint.pk_from_reference(query)
        qs = qs.filter(
            Q(pk=pk) if pk else Q(description__icontains=query) | Q(location__icontains=query) | Q(citizen__username__icontains=query)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page", 1))

    return render(
        request,
        "complaints/admin_list.html",
        {
            "complaints": page_obj,
            "page_obj": page_obj,
            "categories": Category.objects.all(),
            "statuses": Complaint.Status.choices,
            "priorities": Complaint.Priority.choices,
            "active_status": status,
            "active_category": int(category_id) if category_id.isdigit() else "",
            "active_priority": priority,
            "active_ward": ward,
            "query": query,
            "needs_review_filter": request.GET.get("needs_review") == "1",
            "total_count": paginator.count,
        },
    )


@role_required(User.Role.ADMIN)
def admin_map_view(request):
    """Interactive live map of geo-tagged grievances (REQ-DASH-2)."""
    categories = Category.objects.all()
    return render(
        request,
        "complaints/admin_map.html",
        {
            "categories": categories,
            "statuses": Complaint.Status.choices,
        },
    )


@role_required(User.Role.ADMIN)
def admin_analytics(request):
    """Live analytics dashboard & reporting metrics (REQ-REP / 4.10)."""
    total = Complaint.objects.count()
    status_counts = dict(
        Complaint.objects.values("status").annotate(count=Count("id")).values_list("status", "count")
    )
    priority_counts = dict(
        Complaint.objects.values("priority").annotate(count=Count("id")).values_list("priority", "count")
    )

    category_data = list(
        Complaint.objects.values("category__name").annotate(count=Count("id")).order_by("-count")[:10]
    )

    ward_data = list(
        Complaint.objects.values("ward").annotate(count=Count("id")).order_by("-count")[:10]
    )

    # Officers performance
    officers = (
        User.objects.filter(role=User.Role.OFFICER)
        .select_related("officer_profile")
        .annotate(
            assigned_total=Count("assigned_complaints"),
            resolved_total=Count("assigned_complaints", filter=Q(assigned_complaints__status__in=["resolved", "closed"])),
        )
    )

    # Average resolution time
    resolved_qs = Complaint.objects.filter(resolution_time__isnull=False)
    avg_sec = (
        sum(c.resolution_time.total_seconds() for c in resolved_qs) / resolved_qs.count()
        if resolved_qs.exists() else 0
    )
    avg_hours = round(avg_sec / 3600, 1)

    # SLA breaches
    all_complaints = list(Complaint.objects.select_related("category"))
    sla_breaches = sum(1 for c in all_complaints if c.is_sla_breached)

    avg_rating = Feedback.objects.aggregate(Avg("rating"))["rating__avg"] or 0.0

    return render(
        request,
        "complaints/admin_analytics.html",
        {
            "summary": {
                "total": total,
                "open": sum(status_counts.get(s, 0) for s in ["submitted", "assigned", "acknowledged", "in_progress", "reopened"]),
                "resolved": status_counts.get("resolved", 0),
                "closed": status_counts.get("closed", 0),
                "reopened": status_counts.get("reopened", 0),
                "sla_breaches": sla_breaches,
                "avg_hours": avg_hours,
                "avg_rating": round(float(avg_rating), 2),
            },
            "status_counts": status_counts,
            "priority_counts": priority_counts,
            "category_data": category_data,
            "ward_data": ward_data,
            "officers": officers,
            "recent_feedbacks": Feedback.objects.select_related("complaint", "citizen")[:10],
        },
    )


@role_required(User.Role.ADMIN)
def export_csv(request):
    """Export grievances to CSV (REQ-REP-003)."""
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="complaints_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        "Reference", "Citizen", "Category", "Priority", "Status", "Ward", "Location",
        "Assigned Officer", "Submitted At", "Resolved At", "SLA Breached"
    ])

    for c in Complaint.objects.select_related("citizen", "assigned_officer", "category"):
        writer.writerow([
            c.reference,
            c.citizen.username,
            c.category.name if c.category else "Uncategorized",
            c.get_priority_display(),
            c.get_status_display(),
            c.ward,
            c.location,
            c.assigned_officer.username if c.assigned_officer else "None",
            c.submitted_at.strftime("%Y-%m-%d %H:%M:%S"),
            c.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if c.resolved_at else "N/A",
            "Yes" if c.is_sla_breached else "No",
        ])
    return response


@role_required(User.Role.ADMIN)
def export_pdf(request):
    """Export grievances summary report to PDF (REQ-REP-003)."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()

    elements = []
    elements.append(Paragraph("<b>Municipal Grievance Redressal System — Summary Report</b>", styles["Title"]))
    elements.append(Spacer(1, 12))

    total = Complaint.objects.count()
    open_c = Complaint.objects.exclude(status__in=["resolved", "closed"]).count()
    resolved_c = Complaint.objects.filter(status__in=["resolved", "closed"]).count()
    summary_text = f"Generated on {timezone.now().strftime('%d %B %Y, %H:%M')}. Total Complaints: {total} | Open: {open_c} | Resolved: {resolved_c}"
    elements.append(Paragraph(summary_text, styles["Normal"]))
    elements.append(Spacer(1, 16))

    table_data = [["ID", "Category", "Ward", "Priority", "Status", "Date"]]
    for c in Complaint.objects.select_related("category")[:50]:
        table_data.append([
            c.reference,
            (c.category.name[:18] + "..") if c.category and len(c.category.name) > 18 else (c.category.name if c.category else "Uncat"),
            c.ward,
            c.get_priority_display(),
            c.get_status_display(),
            c.submitted_at.strftime("%d/%m/%Y"),
        ])

    table = Table(table_data, colWidths=[70, 140, 80, 70, 90, 80])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1f4fd8')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f6f7f9')])
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)
    response = HttpResponse(buffer, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="grievance_report.pdf"'
    return response


@role_required(User.Role.ADMIN)
def admin_officer_roster(request):
    """View and manage officer roster and availability (SRS 2.2)."""
    officers = User.objects.filter(role=User.Role.OFFICER).select_related("officer_profile")
    return render(request, "complaints/admin_officers.html", {"officers": officers})


@role_required(User.Role.ADMIN)
@require_POST
def admin_toggle_officer_status(request, pk):
    """Toggle officer availability status between active and inactive."""
    officer = get_object_or_404(User, pk=pk, role=User.Role.OFFICER)
    profile = officer.officer_profile
    if profile.availability_status == OfficerProfile.Availability.ACTIVE:
        profile.availability_status = OfficerProfile.Availability.INACTIVE
        messages.warning(request, f"Officer {officer.username} marked as Inactive.")
    else:
        profile.availability_status = OfficerProfile.Availability.ACTIVE
        messages.success(request, f"Officer {officer.username} marked as Active.")
    profile.save()
    return redirect("complaints:admin_officer_roster")


@role_required(User.Role.ADMIN)
def admin_notification_logs(request):
    """View notification logs and delivery statuses (REQ-NOT-004/005)."""
    logs = NotificationLog.objects.select_related("complaint")[:100]
    failed_count = NotificationLog.objects.filter(status="failed").count()
    return render(
        request,
        "complaints/admin_notifications.html",
        {"logs": logs, "failed_count": failed_count},
    )


@role_required(User.Role.ADMIN)
@require_POST
def admin_retry_notifications(request):
    """Trigger retry of failed notifications."""
    count = notifications.retry_failed_notifications()
    messages.success(request, f"Retried {count} pending/failed notification(s).")
    return redirect("complaints:admin_notification_logs")
