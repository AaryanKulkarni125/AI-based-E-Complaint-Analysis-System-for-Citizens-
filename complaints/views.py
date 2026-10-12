from django.contrib import messages
from django.db.models import Case, IntegerField, Q, Value, When
from django.http import FileResponse, Http404, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from accounts.decorators import role_required
from accounts.models import User

from . import services
from .forms import ComplaintForm, OfficerUpdateForm
from .models import Attachment, Complaint


def visible_complaints(user):
    """REQ-TRK-004 / business rules: citizens see their own, officers see what is assigned to them."""
    if user.role == User.Role.CITIZEN:
        return Complaint.objects.filter(citizen=user)
    if user.role == User.Role.OFFICER:
        return Complaint.objects.filter(assigned_officer=user)
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
        )
        messages.success(
            request,
            f"Your complaint has been submitted. Your tracking ID is {complaint.reference}.",
        )
        return redirect("complaints:detail", pk=complaint.pk)
    return render(request, "complaints/submit.html", {"form": form})


@role_required(User.Role.CITIZEN)
def my_list(request):
    complaints = Complaint.objects.filter(citizen=request.user).select_related("assigned_officer")

    status = request.GET.get("status", "")
    if status in Complaint.Status.values:
        complaints = complaints.filter(status=status)
    else:
        status = ""

    query = request.GET.get("q", "").strip()
    if query:
        pk = Complaint.pk_from_reference(query)
        complaints = complaints.filter(Q(pk=pk) if pk else Q(description__icontains=query))

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
    """REQ-OFF-001..004: only my complaints, sortable and filterable, with pending/resolved counts."""
    mine = Complaint.objects.filter(assigned_officer=request.user).select_related("citizen")
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


@role_required(User.Role.CITIZEN, User.Role.OFFICER)
def detail(request, pk):
    # 404 (not 403) when it isn't yours, so IDs of other people's complaints aren't confirmed.
    complaint = get_object_or_404(
        visible_complaints(request.user).select_related("assigned_officer", "resolved_by"), pk=pk
    )

    update_form = None
    if request.user.role == User.Role.OFFICER and complaint.next_officer_statuses:
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
                        request, f"{complaint.reference} updated to "
                        f"\"{Complaint.Status(update_form.cleaned_data['status']).label}\"."
                    )
                return redirect("complaints:detail", pk=complaint.pk)
        else:
            update_form = OfficerUpdateForm(complaint)
    elif request.method == "POST":
        return HttpResponseNotAllowed(["GET"])

    return render(
        request,
        "complaints/detail.html",
        {
            "complaint": complaint,
            "history": complaint.history.select_related("changed_by"),
            "attachments": complaint.attachments.all(),
            "update_form": update_form,
        },
    )


@role_required(User.Role.CITIZEN, User.Role.OFFICER)
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
