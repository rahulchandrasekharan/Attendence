import calendar
import datetime as dt
import json

import numpy as np
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import ProtectedError, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font

from . import face_engine, services
from .forms import BatchForm, MentorSignupForm, StudentEditForm, StudentSignupForm
from .models import Attendance, Batch, Student, StudentPhoto
from .roles import is_team_lead, team_lead_required

MIN_PHOTOS = 3


# ---------------------------------------------------------------- public pages

def home(request):
    return render(request, "core/home.html", {"now": services.now_local()})


def punch(request):
    return render(request, "core/punch.html", {"now": services.now_local()})


@require_POST
def api_punch(request):
    try:
        image = json.loads(request.body).get("image")
    except (ValueError, AttributeError):
        image = None
    if not image:
        return JsonResponse({"ok": False, "message": "No image received.", "kind": "error"}, status=400)
    return JsonResponse(services.punch_in(image).as_dict())


def student_signup(request):
    form = StudentSignupForm(request.POST or None)
    if request.method == "POST":
        images = [v for k, v in request.POST.items() if k.startswith("photo_") and v]
        images += [f.read() for f in request.FILES.getlist("uploads")]
        embeddings, crops, photo_errors = [], [], []
        for i, data in enumerate(images, 1):
            try:
                img = face_engine.decode_image(data)
                emb, face = face_engine.embed(img)
                embeddings.append(emb)
                crops.append(face_engine.crop_jpeg(img, face, pad=0.5))
            except face_engine.FaceError as e:
                photo_errors.append(f"Photo {i}: {e}")

        if form.is_valid():
            if len(embeddings) < MIN_PHOTOS:
                form.add_error(None, f"We need at least {MIN_PHOTOS} clear photos with your face "
                                     f"(got {len(embeddings)} usable).")
            else:
                # The photos must agree with each other (same person in every shot).
                E = np.stack(embeddings)
                sims = E @ E.T
                if sims[np.triu_indices(len(E), 1)].min() < 0.3:
                    form.add_error(None, "The photos don't look like the same person. Please retake them.")
                else:
                    mean = E.mean(axis=0)
                    dup, _ = face_engine.best_match(mean / np.linalg.norm(mean), Student.objects.filter(is_active=True))
                    if dup:
                        form.add_error(None, f"This face is already registered (ID {dup.student_id}). "
                                             "Ask your mentor if you need to change batch.")
            if not form.errors:
                with transaction.atomic():
                    student = form.save(commit=False)
                    student.set_embeddings(E)
                    student.save()
                    for n, crop in enumerate(crops):
                        if crop:
                            p = StudentPhoto(student=student)
                            p.image.save(f"{student.student_id}_{n}.jpg", ContentFile(crop))
                return render(request, "core/signup_done.html", {"student": student})
        for e in photo_errors:
            messages.warning(request, e)
    return render(request, "core/student_signup.html", {"form": form, "min_photos": MIN_PHOTOS})


def mentor_signup(request):
    form = MentorSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, "Welcome! Start by creating your batches.")
        return redirect("batch_create")
    return render(request, "registration/mentor_signup.html", {"form": form})


# ---------------------------------------------------------------- mentor pages

@login_required
def dashboard(request):
    now = services.now_local()
    today = now.date()
    cards = []
    for b in request.user.batches.all():
        _, rows = services.register_rows(b, today, today)
        codes = [r["codes"][0] for r in rows]
        cards.append({
            "batch": b, "runs_today": b.runs_on(today),
            "students": b.students.filter(is_active=True).count(),
            "present": codes.count("P"), "late": codes.count("L"), "absent": codes.count("A"),
            "pending": sum(1 for r, c in zip(rows, codes) if c == "" and r["student"].batch_id == b.id),
        })
    recent = Attendance.objects.filter(batch__mentor=request.user, date=today).select_related("student", "batch")
    return render(request, "core/dashboard.html", {"cards": cards, "recent": recent, "now": now})


@login_required
def batch_form(request, pk=None):
    batch = get_object_or_404(Batch, pk=pk, mentor=request.user) if pk else Batch(mentor=request.user)
    form = BatchForm(request.POST or None, instance=batch, mentor=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Batch '{batch.name}' saved.")
        return redirect("batch_detail", pk=batch.pk)
    return render(request, "core/batch_form.html", {"form": form, "batch": batch})


@login_required
@require_POST
def batch_delete(request, pk):
    batch = get_object_or_404(Batch, pk=pk, mentor=request.user)
    try:
        batch.delete()
        messages.success(request, "Batch deleted.")
    except ProtectedError:
        messages.error(request, "Move or remove this batch's students before deleting it.")
        return redirect("batch_detail", pk=pk)
    return redirect("dashboard")


def _month_param(request):
    try:
        y, m = map(int, request.GET.get("month", "").split("-"))
        return dt.date(y, m, 1)
    except ValueError:
        return services.now_local().date().replace(day=1)


def _viewable_batch(user, pk):
    """Trainers see only their own batches; team leads can open any batch (read-only)."""
    if is_team_lead(user):
        return get_object_or_404(Batch.objects.select_related("mentor"), pk=pk)
    return get_object_or_404(Batch, pk=pk, mentor=user)


@login_required
def batch_detail(request, pk):
    batch = _viewable_batch(request.user, pk)
    month = _month_param(request)
    last = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    dates, rows = services.register_rows(batch, month, last)
    stats = [services.student_stats(s) for s in batch.students.filter(is_active=True).select_related("batch")]
    stats.sort(key=lambda s: (s["percent"] is None, s["percent"] if s["percent"] is not None else 0))
    labels, p, l, a = services.batch_daily_trend(batch)
    prev_m = (month - dt.timedelta(days=1)).replace(day=1)
    next_m = last + dt.timedelta(days=1)
    today = services.now_local().date()
    marked_today = set(Attendance.objects.filter(date=today, student__batch=batch).values_list("student_id", flat=True))
    is_today = [d == today for d in dates]
    for r in rows:
        r["cells"] = list(zip(r["codes"], is_today))
    return render(request, "core/batch_detail.html", {
        "batch": batch, "month": month, "dates": list(zip(dates, is_today)), "rows": rows, "stats": stats,
        "prev_month": f"{prev_m:%Y-%m}", "next_month": f"{next_m:%Y-%m}",
        "today": today, "students": batch.students.all(), "marked_today": marked_today,
        "can_edit": batch.mentor_id == request.user.id,
        "chart": json.dumps({"labels": labels, "present": p, "late": l, "absent": a}),
    })


@login_required
def download_register(request, pk):
    batch = _viewable_batch(request.user, pk)
    month = _month_param(request)
    wb = services.build_workbook(batch, month.year, month.month)
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{services._safe(batch.name)}_{month:%Y-%m}.xlsx"'
    wb.save(resp)
    return resp


@login_required
def student_edit(request, pk):
    student = get_object_or_404(Student, pk=pk, batch__mentor=request.user)
    old_batch = student.batch
    form = StudentEditForm(request.POST or None, instance=student, mentor=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        today = services.now_local().date()
        for b in {old_batch, student.batch}:
            services.write_register(b, today)
        messages.success(request, f"{student.full_name} updated.")
        return redirect("batch_detail", pk=student.batch_id)
    return render(request, "core/student_edit.html", {"form": form, "student": student})


@login_required
@require_POST
def manual_mark(request, pk):
    """Mentor marks a student present/late for today (e.g. camera problems)."""
    student = get_object_or_404(Student, pk=pk, batch__mentor=request.user)
    now = services.now_local()
    status = request.POST.get("status", Attendance.PRESENT)
    if status not in (Attendance.PRESENT, Attendance.LATE):
        status = Attendance.PRESENT
    _, created = Attendance.objects.get_or_create(
        student=student, date=now.date(),
        defaults={"batch": student.batch, "time_in": now.time().replace(microsecond=0),
                  "status": status, "method": "manual"},
    )
    services.write_register(student.batch, now.date())
    if created:
        messages.success(request, f"{student.full_name} marked {dict(Attendance.STATUS_CHOICES)[status]} manually.")
    else:
        messages.info(request, f"{student.full_name} is already marked today.")
    return redirect("batch_detail", pk=student.batch_id)


# ---------------------------------------------------------------- team lead

def _lead_report(request):
    """Shared filtering for the team-lead page and its Excel export."""
    f = request.GET
    try:
        days = int(f.get("days", 30))
    except ValueError:
        days = 30
    days = days if days in (7, 30, 90) else 30
    trainers = User.objects.filter(batches__isnull=False).distinct().order_by("first_name", "username")
    students = Student.objects.filter(is_active=True).select_related("batch__mentor").order_by("full_name")
    batches = Batch.objects.select_related("mentor").order_by("mentor__username", "start_time")
    trainer_id = f.get("trainer", "")
    if trainer_id.isdigit():
        students = students.filter(batch__mentor_id=trainer_id)
        batches = batches.filter(mentor_id=trainer_id)
    batch_id = f.get("batch", "")
    if batch_id.isdigit():
        students = students.filter(batch_id=batch_id)
    q = f.get("q", "").strip()
    if q:
        students = students.filter(Q(full_name__icontains=q) | Q(student_id__icontains=q))

    today = services.now_local().date()
    today_recs = {a.student_id: a for a in Attendance.objects.filter(date=today, student__in=students)}
    stats = []
    for s in students:
        st = services.student_stats(s, days=days)
        st["today"] = services.day_status(s, s.batch, today, {(s.id, today): today_recs[s.id]} if s.id in today_recs else {})
        stats.append(st)
    risk = f.get("risk", "")
    if risk in ("low", "medium", "high"):
        stats = [s for s in stats if s["risk"] == risk]
    stats.sort(key=lambda s: (s["student"].batch.mentor.username, s["percent"] is None, s["percent"] or 0))

    # One summary card per trainer, built from the (filtered) student rows.
    summary = {}
    if not (batch_id.isdigit() or q or risk):  # list every trainer, even ones with no students yet
        for m in (trainers.filter(id=trainer_id) if trainer_id.isdigit() else trainers):
            summary[m.id] = {"trainer": m, "students": 0, "P": 0, "L": 0, "A": 0, "high": 0, "pcts": []}
    for s in stats:
        m = s["student"].batch.mentor
        c = summary.setdefault(m.id, {"trainer": m, "students": 0, "P": 0, "L": 0, "A": 0, "high": 0, "pcts": []})
        c["students"] += 1
        if s["today"] in ("P", "L", "A"):
            c[s["today"]] += 1
        c["high"] += s["risk"] == "high"
        if s["percent"] is not None:
            c["pcts"].append(s["percent"])
    for c in summary.values():
        c["avg"] = round(sum(c["pcts"]) / len(c["pcts"]), 1) if c["pcts"] else None
        c["batches"] = c["trainer"].batches.count()
    return {
        "stats": stats, "summary": list(summary.values()), "trainers": trainers, "batches": batches,
        "f": {"trainer": trainer_id, "batch": batch_id, "risk": risk, "q": q, "days": days},
        "today": today,
    }


@team_lead_required
def lead_overview(request):
    ctx = _lead_report(request)
    ctx["query"] = request.GET.urlencode()
    return render(request, "core/lead_overview.html", ctx)


@team_lead_required
def lead_export(request):
    ctx = _lead_report(request)
    wb = Workbook()
    ws = wb.active
    ws.title = "Student report"
    ws.append([f"Student report · last {ctx['f']['days']} days · generated {services.now_local():%d %b %Y %H:%M}"])
    ws.append(["Trainer", "Batch", "Timing", "Student ID", "Name", "Today", "Attended", "Class days",
               "Attendance %", "Late", "Avg arrival (min)", "Trend (%/week)", "Risk"])
    for c in ws[2]:
        c.font = Font(bold=True)
    names = {"P": "Present", "L": "Late", "A": "Absent", "-": "No class", "": "Not yet"}
    for s in ctx["stats"]:
        st = s["student"]
        ws.append([st.batch.mentor.get_full_name() or st.batch.mentor.username, st.batch.name,
                   f"{st.start_time:%H:%M}-{st.end_time:%H:%M}", st.student_id, st.full_name,
                   names.get(s["today"], s["today"]), s["attended"], s["scheduled"], s["percent"], s["late"],
                   s["avg_delay"], s["trend"], s["risk"]])
    for col, w in zip("ABCDEFGHIJKLM", (18, 14, 13, 13, 24, 10, 10, 11, 13, 7, 17, 15, 8)):
        ws.column_dimensions[col].width = w
    ws.freeze_panes = "A3"
    resp = HttpResponse(content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="student_report_{ctx["today"]:%Y-%m-%d}.xlsx"'
    wb.save(resp)
    return resp
