"""Centralized REST API views for frontend-backend integration.

Provides JSON request/response handling, standardized error envelopes, authentication
and role-based permissions, pagination, and real-time operations.
"""

import json
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Avg, Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from accounts.models import User

from . import ai, notifications, services
from .models import Category, Complaint, Feedback, NotificationLog, StatusHistory


def api_error(message, status=400, details=None):
    payload = {"status": "error", "message": message}
    if details:
        payload["details"] = details
    return JsonResponse(payload, status=status)


def api_success(data=None, message="Success", status=200):
    payload = {"status": "success", "message": message}
    if data is not None:
        payload["data"] = data
    return JsonResponse(payload, status=status)


def serialize_complaint(c, detail=False):
    base = {
        "id": c.pk,
        "reference": c.reference,
        "description": c.description,
        "location": c.location,
        "ward": c.ward,
        "latitude": float(c.latitude) if c.latitude else None,
        "longitude": float(c.longitude) if c.longitude else None,
        "status": c.status,
        "status_display": c.get_status_display(),
        "priority": c.priority,
        "priority_display": c.get_priority_display(),
        "category": {
            "id": c.category.id,
            "name": c.category.name,
            "department": c.category.department_name,
            "sla_hours": c.category.sla_hours,
        } if c.category else None,
        "confidence_score": c.confidence_score,
        "needs_review": c.needs_review,
        "is_duplicate": c.is_duplicate,
        "duplicate_of": c.duplicate_of.reference if c.duplicate_of else None,
        "citizen": {
            "id": c.citizen.id,
            "username": c.citizen.username,
            "name": c.citizen.get_full_name() or c.citizen.username,
        },
        "assigned_officer": {
            "id": c.assigned_officer.id,
            "username": c.assigned_officer.username,
            "name": c.assigned_officer.get_full_name() or c.assigned_officer.username,
        } if c.assigned_officer else None,
        "submitted_at": c.submitted_at.isoformat(),
        "updated_at": c.updated_at.isoformat(),
        "is_sla_breached": c.is_sla_breached,
        "sla_remaining_hours": c.sla_remaining_hours,
        "can_be_reopened": c.can_be_reopened,
    }

    if detail:
        base.update({
            "resolution_remarks": c.resolution_remarks,
            "resolved_at": c.resolved_at.isoformat() if c.resolved_at else None,
            "resolved_by": c.resolved_by.username if c.resolved_by else None,
            "resolution_time_seconds": c.resolution_time.total_seconds() if c.resolution_time else None,
            "closure_remarks": c.closure_remarks,
            "closed_at": c.closed_at.isoformat() if c.closed_at else None,
            "closed_by": c.closed_by.username if c.closed_by else None,
            "history": [
                {
                    "from_status": h.from_status,
                    "to_status": h.to_status,
                    "changed_by": h.changed_by.username if h.changed_by else "System",
                    "note": h.note,
                    "timestamp": h.timestamp.isoformat(),
                }
                for h in c.history.all()
            ],
            "attachments": [
                {
                    "id": a.pk,
                    "name": a.original_name,
                    "size": a.size,
                    "is_evidence": a.is_resolution_evidence,
                    "uploaded_at": a.uploaded_at.isoformat(),
                }
                for a in c.attachments.all()
            ],
            "feedback": {
                "rating": c.feedback.rating,
                "comments": c.feedback.comments,
                "created_at": c.feedback.created_at.isoformat(),
            } if hasattr(c, "feedback") else None,
        })
    return base


@require_http_methods(["GET", "POST"])
def complaints_collection(request):
    """GET: List complaints accessible to user. POST: Submit a new complaint."""
    if not request.user.is_authenticated:
        return api_error("Authentication required.", status=401)

    if request.method == "GET":
        user = request.user
        if user.is_system_admin:
            qs = Complaint.objects.all()
        elif user.is_officer:
            qs = Complaint.objects.filter(assigned_officer=user)
        else:
            qs = Complaint.objects.filter(citizen=user)

        qs = qs.select_related("citizen", "assigned_officer", "category", "duplicate_of")

        # Filters
        status = request.GET.get("status")
        if status in Complaint.Status.values:
            qs = qs.filter(status=status)

        category_id = request.GET.get("category")
        if category_id and category_id.isdigit():
            qs = qs.filter(category_id=int(category_id))

        ward = request.GET.get("ward")
        if ward:
            qs = qs.filter(ward__iexact=ward.strip())

        q = request.GET.get("q", "").strip()
        if q:
            pk = Complaint.pk_from_reference(q)
            qs = qs.filter(Q(pk=pk) if pk else Q(description__icontains=q) | Q(location__icontains=q))

        # Pagination
        page = request.GET.get("page", 1)
        paginator = Paginator(qs, 20)
        p = paginator.get_page(page)

        return api_success({
            "items": [serialize_complaint(c) for c in p.object_list],
            "total": paginator.count,
            "page": p.number,
            "pages": paginator.num_pages,
            "has_next": p.has_next(),
            "has_prev": p.has_previous(),
        })

    # POST: Submit new complaint (Citizen only)
    if not request.user.is_citizen:
        return api_error("Only citizens can submit complaints.", status=403)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        description = body.get("description", "").strip()
        location = body.get("location", "").strip()
        ward = body.get("ward", "Ward 1").strip()
        lat = body.get("latitude")
        lng = body.get("longitude")
        cat_id = body.get("category_id")
    else:
        description = request.POST.get("description", "").strip()
        location = request.POST.get("location", "").strip()
        ward = request.POST.get("ward", "Ward 1").strip()
        lat = request.POST.get("latitude")
        lng = request.POST.get("longitude")
        cat_id = request.POST.get("category_id")

    if len(description) < 20:
        return api_error("Description must be at least 20 characters.", details={"description": "Too short"})
    if not location:
        return api_error("Location is required.", details={"location": "Required"})

    category = None
    if cat_id:
        category = Category.objects.filter(pk=cat_id).first()

    latitude = Decimal(str(lat)) if lat else None
    longitude = Decimal(str(lng)) if lng else None

    files = request.FILES.getlist("attachments")

    try:
        complaint = services.create_complaint(
            citizen=request.user,
            description=description,
            location=location,
            files=files,
            ward=ward,
            latitude=latitude,
            longitude=longitude,
            category=category,
        )
    except Exception as exc:
        return api_error(f"Failed to submit complaint: {exc}", status=500)

    return api_success(serialize_complaint(complaint, detail=True), message="Complaint submitted successfully", status=201)


@require_http_methods(["GET"])
def complaint_detail(request, pk):
    """GET single complaint details."""
    if not request.user.is_authenticated:
        return api_error("Authentication required.", status=401)

    c = Complaint.objects.filter(pk=pk).select_related(
        "citizen", "assigned_officer", "category", "resolved_by", "closed_by", "feedback"
    ).prefetch_related("history__changed_by", "attachments").first()

    if not c:
        return api_error("Complaint not found.", status=404)

    user = request.user
    if user.is_citizen and c.citizen_id != user.pk:
        return api_error("Complaint not found.", status=404)
    if user.is_officer and c.assigned_officer_id != user.pk:
        return api_error("Complaint not found.", status=404)

    return api_success(serialize_complaint(c, detail=True))


@require_http_methods(["POST"])
def update_status_api(request, pk):
    """Officer status transition (REQ-WFL-003, REQ-RES-001..003)."""
    if not request.user.is_authenticated:
        return api_error("Authentication required.", status=401)
    if not request.user.is_officer:
        return api_error("Only assigned officers can update complaint status.", status=403)

    c = Complaint.objects.filter(pk=pk).first()
    if not c or c.assigned_officer_id != request.user.pk:
        return api_error("Complaint not found or not assigned to you.", status=404)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        new_status = body.get("status")
        remarks = body.get("remarks", "")
    else:
        new_status = request.POST.get("status")
        remarks = request.POST.get("remarks", "")

    evidence = request.FILES.getlist("evidence")

    try:
        updated = services.change_status(c, request.user, new_status, remarks=remarks, evidence=evidence)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)
    except Exception as exc:
        return api_error(f"Status update failed: {exc}", status=500)

    return api_success(serialize_complaint(updated, detail=True), message="Status updated successfully.")


@require_http_methods(["POST"])
def reassign_api(request, pk):
    """Admin manual reassignment with audit reason (REQ-ASGN-2)."""
    if not request.user.is_authenticated or not request.user.is_system_admin:
        return api_error("Administrator permission required.", status=403)

    c = Complaint.objects.filter(pk=pk).first()
    if not c:
        return api_error("Complaint not found.", status=404)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        officer_id = body.get("officer_id")
        reason = body.get("reason", "").strip()
    else:
        officer_id = request.POST.get("officer_id")
        reason = request.POST.get("reason", "").strip()

    if not reason:
        return api_error("Reassignment reason is mandatory.")

    officer = User.objects.filter(pk=officer_id, role=User.Role.OFFICER, is_active=True).first()
    if not officer:
        return api_error("Target officer must be an active officer.")

    try:
        updated = services.admin_reassign_complaint(c, officer, request.user, reason)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)

    return api_success(serialize_complaint(updated, detail=True), message=f"Reassigned to officer {officer.username}.")


@require_http_methods(["POST"])
def override_ai_api(request, pk):
    """Admin override of AI category and priority with audit logging (REQ-AI-004/005)."""
    if not request.user.is_authenticated or not request.user.is_system_admin:
        return api_error("Administrator permission required.", status=403)

    c = Complaint.objects.filter(pk=pk).first()
    if not c:
        return api_error("Complaint not found.", status=404)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        category_id = body.get("category_id")
        priority = body.get("priority")
        reason = body.get("reason", "")
    else:
        category_id = request.POST.get("category_id")
        priority = request.POST.get("priority")
        reason = request.POST.get("reason", "")

    category = Category.objects.filter(pk=category_id).first()
    if not category:
        return api_error("Valid category is required.")
    if priority not in Complaint.Priority.values:
        return api_error("Valid priority is required (high, medium, low).")

    try:
        updated = services.admin_override_ai(c, category, priority, request.user, reason)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)

    return api_success(serialize_complaint(updated, detail=True), message="AI prediction overridden successfully.")


@require_http_methods(["POST"])
def close_complaint_api(request, pk):
    """Admin marks resolved complaint as closed (REQ-RES-004)."""
    if not request.user.is_authenticated or not request.user.is_system_admin:
        return api_error("Administrator permission required.", status=403)

    c = Complaint.objects.filter(pk=pk).first()
    if not c:
        return api_error("Complaint not found.", status=404)

    remarks = request.POST.get("remarks", "")
    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
            remarks = body.get("remarks", "")
        except ValueError:
            pass

    try:
        updated = services.admin_close_complaint(c, request.user, remarks)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)

    return api_success(serialize_complaint(updated, detail=True), message="Complaint marked as closed.")


@require_http_methods(["POST"])
def feedback_api(request, pk):
    """Citizen submits rating and remarks upon resolution (REQ-FDBK-1)."""
    if not request.user.is_authenticated:
        return api_error("Authentication required.", status=401)

    c = Complaint.objects.filter(pk=pk).first()
    if not c:
        return api_error("Complaint not found.", status=404)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        rating = body.get("rating", 5)
        comments = body.get("comments", "")
    else:
        rating = request.POST.get("rating", 5)
        comments = request.POST.get("comments", "")

    try:
        fb = services.submit_citizen_feedback(c, request.user, rating, comments)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)

    return api_success({
        "rating": fb.rating,
        "comments": fb.comments,
        "created_at": fb.created_at.isoformat(),
    }, message="Feedback submitted successfully.")


@require_http_methods(["POST"])
def reopen_api(request, pk):
    """Citizen reopens unsatisfied grievance within 7 days (REQ-FDBK-2)."""
    if not request.user.is_authenticated:
        return api_error("Authentication required.", status=401)

    c = Complaint.objects.filter(pk=pk).first()
    if not c:
        return api_error("Complaint not found.", status=404)

    if request.content_type and "application/json" in request.content_type:
        try:
            body = json.loads(request.body.decode("utf-8"))
        except ValueError:
            return api_error("Malformed JSON.")
        reason = body.get("reason", "").strip()
    else:
        reason = request.POST.get("reason", "").strip()

    try:
        updated = services.reopen_complaint(c, request.user, reason)
    except services.WorkflowError as exc:
        return api_error(str(exc), status=400)

    return api_success(serialize_complaint(updated, detail=True), message="Complaint reopened successfully.")


@require_http_methods(["GET"])
def map_data_api(request):
    """Public/Admin endpoint for geo-tagged complaint markers on live map (REQ-DASH-2)."""
    qs = Complaint.objects.filter(latitude__isnull=False, longitude__isnull=False).select_related("category")

    status = request.GET.get("status")
    if status in Complaint.Status.values:
        qs = qs.filter(status=status)

    ward = request.GET.get("ward")
    if ward:
        qs = qs.filter(ward__iexact=ward.strip())

    category_id = request.GET.get("category")
    if category_id and category_id.isdigit():
        qs = qs.filter(category_id=int(category_id))

    markers = [
        {
            "id": c.pk,
            "reference": c.reference,
            "latitude": float(c.latitude),
            "longitude": float(c.longitude),
            "status": c.status,
            "status_display": c.get_status_display(),
            "priority": c.priority,
            "category": c.category.name if c.category else "General",
            "ward": c.ward,
            "location": c.location,
            "description": c.description[:120] + ("..." if len(c.description) > 120 else ""),
            "submitted_at": c.submitted_at.strftime("%d %b %Y"),
        }
        for c in qs[:200]
    ]
    return api_success(markers)


@require_http_methods(["GET"])
def analytics_api(request):
    """Live analytics data for dashboard charts (REQ-REP / 4.10)."""
    if not request.user.is_authenticated or not request.user.is_system_admin:
        return api_error("Administrator permission required.", status=403)

    total = Complaint.objects.count()
    status_counts = dict(
        Complaint.objects.values("status").annotate(count=Count("id")).values_list("status", "count")
    )
    priority_counts = dict(
        Complaint.objects.values("priority").annotate(count=Count("id")).values_list("priority", "count")
    )

    category_counts = [
        {"name": c["category__name"] or "Uncategorized", "count": c["count"]}
        for c in Complaint.objects.values("category__name").annotate(count=Count("id")).order_by("-count")[:10]
    ]

    ward_counts = [
        {"ward": w["ward"] or "Unassigned", "count": w["count"]}
        for w in Complaint.objects.values("ward").annotate(count=Count("id")).order_by("-count")[:10]
    ]

    # Average resolution time
    resolved_complaints = Complaint.objects.filter(resolution_time__isnull=False)
    avg_sec = (
        sum(c.resolution_time.total_seconds() for c in resolved_complaints) / resolved_complaints.count()
        if resolved_complaints.exists() else 0
    )
    avg_hours = round(avg_sec / 3600, 1)

    # SLA Breaches count
    all_complaints = Complaint.objects.select_related("category")
    sla_breached_count = sum(1 for c in all_complaints if c.is_sla_breached)

    # Feedback average
    avg_rating = Feedback.objects.aggregate(Avg("rating"))["rating__avg"] or 0.0

    return api_success({
        "summary": {
            "total": total,
            "open": sum(status_counts.get(s, 0) for s in ["submitted", "assigned", "acknowledged", "in_progress", "reopened"]),
            "resolved": status_counts.get("resolved", 0),
            "closed": status_counts.get("closed", 0),
            "reopened": status_counts.get("reopened", 0),
            "sla_breached": sla_breached_count,
            "avg_resolution_hours": avg_hours,
            "avg_satisfaction_rating": round(float(avg_rating), 2),
        },
        "by_status": status_counts,
        "by_priority": priority_counts,
        "by_category": category_counts,
        "by_ward": ward_counts,
    })


@require_http_methods(["GET"])
def categories_list_api(request):
    """List all categories with SLA hours."""
    cats = [
        {
            "id": c.pk,
            "name": c.name,
            "department": c.department_name,
            "sla_hours": c.sla_hours,
            "description": c.description,
        }
        for c in Category.objects.all()
    ]
    return api_success(cats)
