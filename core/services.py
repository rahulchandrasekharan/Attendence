"""Attendance rules, Excel register files and analytics."""
import calendar
import datetime as dt
import re

import numpy as np
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import IntegrityError
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import face_engine
from .models import Attendance, Student


def now_local():
    return timezone.localtime()


def _combine(date, t):
    return dt.datetime.combine(date, t)


# ---------------------------------------------------------------- punch-in rules

class PunchResult:
    def __init__(self, ok, message, student=None, record=None, score=None, kind="error"):
        self.ok, self.message, self.student, self.record, self.score, self.kind = ok, message, student, record, score, kind

    def as_dict(self):
        d = {"ok": self.ok, "message": self.message, "kind": self.kind}
        if self.score is not None:
            d["confidence"] = round(self.score, 3)
        if self.student:
            d["student"] = {
                "name": self.student.full_name,
                "id": self.student.student_id,
                "batch": self.student.batch.name,
                "timing": f"{self.student.start_time:%I:%M %p} - {self.student.end_time:%I:%M %p}",
            }
        if self.record:
            d["status"] = self.record.get_status_display()
            d["time_in"] = self.record.time_in.strftime("%I:%M %p")
            d["date"] = self.record.date.strftime("%d %b %Y")
        return d


def check_window(student, when):
    """Return (allowed, status_or_message) for a student punching at local datetime `when`."""
    today = when.date()
    if not student.batch.runs_on(today):
        return False, f"{student.batch.name} has no class today ({today:%A})."
    start = _combine(today, student.start_time)
    end = _combine(today, student.end_time)
    opens = start - dt.timedelta(minutes=settings.PUNCH_OPEN_BEFORE_MIN)
    naive = when.replace(tzinfo=None)
    if naive < opens:
        return False, f"Too early. Your batch starts at {start:%I:%M %p}; punch-in opens at {opens:%I:%M %p}."
    if naive > end:
        return False, f"Your batch time ({start:%I:%M %p} - {end:%I:%M %p}) is over for today."
    late = naive > start + dt.timedelta(minutes=settings.LATE_AFTER_MIN)
    return True, Attendance.LATE if late else Attendance.PRESENT


def punch_in(image_data):
    try:
        img = face_engine.decode_image(image_data)
        emb, face = face_engine.embed(img, require_single=True)
    except face_engine.FaceError as e:
        return PunchResult(False, str(e), kind="noface")

    students = Student.objects.filter(is_active=True, batch__is_active=True).select_related("batch")
    student, score = face_engine.best_match(emb, students)
    if student is None:
        return PunchResult(False, "Face not recognised. Please sign up first, or try again facing the camera.",
                           score=score, kind="unknown")

    when = now_local()
    existing = Attendance.objects.filter(student=student, date=when.date()).first()
    if existing:
        return PunchResult(True, f"Already marked today at {existing.time_in:%I:%M %p}.",
                           student, existing, score, kind="duplicate")

    allowed, status = check_window(student, when)
    if not allowed:
        return PunchResult(False, status, student, score=score, kind="window")

    record = Attendance(student=student, batch=student.batch, date=when.date(),
                        time_in=when.time().replace(microsecond=0), status=status,
                        confidence=score, method="face")
    snap = face_engine.crop_jpeg(img, face)
    if snap:
        record.snapshot.save(f"{student.student_id}_{when:%H%M%S}.jpg", ContentFile(snap), save=False)
    try:
        record.save()
    except IntegrityError:  # double click / two kiosks at the same moment
        existing = Attendance.objects.get(student=student, date=when.date())
        return PunchResult(True, "Already marked today.", student, existing, score, kind="duplicate")

    write_register(student.batch, when.date())
    label = "Present" if status == Attendance.PRESENT else "Late"
    return PunchResult(True, f"Welcome {student.full_name}! Marked {label} at {record.time_in:%I:%M %p}.",
                       student, record, score, kind="marked")


# ---------------------------------------------------------------- register (matrix) logic

def day_status(student, batch, date, records, now=None):
    """Code shown in the register: P / L / A / '-' (no class) / '' (not yet / before joining)."""
    now = now or now_local()
    rec = records.get((student.id, date))
    if rec:
        return rec.status
    if not batch.runs_on(date):
        return "-"
    if date < timezone.localtime(student.created_at).date():
        return ""
    if student.batch_id != batch.id:
        return ""  # moved to another batch; only their records count here
    if date > now.date():
        return ""
    if date == now.date() and now.replace(tzinfo=None) <= _combine(date, student.end_time):
        return ""  # class still running today
    return "A"


def register_rows(batch, start, end):
    """Students x dates matrix for one batch between two dates (inclusive)."""
    dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    recs = Attendance.objects.filter(batch=batch, date__range=(start, end)).select_related("student")
    records = {(r.student_id, r.date): r for r in recs}
    ids = set(batch.students.filter(is_active=True).values_list("id", flat=True)) | {r.student_id for r in recs}
    students = Student.objects.filter(id__in=ids).select_related("batch").order_by("full_name")
    now = now_local()
    rows = []
    for s in students:
        codes = [day_status(s, batch, d, records, now) for d in dates]
        counted = [c for c in codes if c in ("P", "L", "A")]
        attended = sum(c in ("P", "L") for c in codes)
        rows.append({
            "student": s, "codes": codes,
            "present": codes.count("P"), "late": codes.count("L"), "absent": codes.count("A"),
            "percent": round(100 * attended / len(counted), 1) if counted else None,
        })
    return dates, rows


_FILL = {
    "P": PatternFill("solid", fgColor="C6EFCE"),
    "L": PatternFill("solid", fgColor="FFEB9C"),
    "A": PatternFill("solid", fgColor="FFC7CE"),
    "-": PatternFill("solid", fgColor="EDEDED"),
}


def _safe(name):
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or "batch"


def build_workbook(batch, year, month):
    first = dt.date(year, month, 1)
    last = dt.date(year, month, calendar.monthrange(year, month)[1])
    dates, rows = register_rows(batch, first, last)

    wb = Workbook()
    ws = wb.active
    ws.title = f"{first:%b %Y}"
    ws.append([f"{batch.name}  |  {batch.start_time:%I:%M %p} - {batch.end_time:%I:%M %p}  |  "
               f"Mentor: {batch.mentor.get_full_name() or batch.mentor.username}  |  {first:%B %Y}"])
    ws["A1"].font = Font(bold=True, size=12)
    header = ["Student ID", "Name", "Timing"] + [d.strftime("%d %a") for d in dates] + ["Present", "Late", "Absent", "Attendance %"]
    ws.append(header)
    for cell in ws[2]:
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal="center", text_rotation=90 if cell.column > 3 else 0)
    for r in rows:
        s = r["student"]
        timing = f"{s.start_time:%H:%M}-{s.end_time:%H:%M}" + (" *" if s.has_custom_timing else "")
        ws.append([s.student_id, s.full_name, timing] + r["codes"] +
                  [r["present"], r["late"], r["absent"], r["percent"]])
        for i, code in enumerate(r["codes"]):
            cell = ws.cell(row=ws.max_row, column=4 + i)
            cell.alignment = Alignment(horizontal="center")
            if code in _FILL:
                cell.fill = _FILL[code]
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 14
    for i in range(len(dates)):
        ws.column_dimensions[get_column_letter(4 + i)].width = 4.5
    ws.freeze_panes = "D3"
    ws.append([])
    ws.append(["P = Present, L = Late, A = Absent, - = No class, * = custom timing"])

    log = wb.create_sheet("Punch log")
    log.append(["Date", "Time in", "Student ID", "Name", "Status", "Method", "Confidence"])
    for c in log[1]:
        c.font = Font(bold=True)
    for a in Attendance.objects.filter(batch=batch, date__range=(first, last)).select_related("student").order_by("date", "time_in"):
        log.append([a.date, a.time_in, a.student.student_id, a.student.full_name,
                    a.get_status_display(), a.get_method_display(),
                    round(a.confidence, 3) if a.confidence is not None else None])
    for col, w in zip("ABCDEFG", (12, 10, 14, 24, 10, 16, 11)):
        log.column_dimensions[col].width = w
    return wb


def register_path(batch, year, month):
    folder = settings.ATTENDANCE_FILES_DIR / _safe(batch.mentor.username)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{_safe(batch.name)}_{year}-{month:02d}.xlsx"


def write_register(batch, date):
    """Rebuild the batch's monthly Excel register on disk (DB is the source of truth)."""
    path = register_path(batch, date.year, date.month)
    try:
        build_workbook(batch, date.year, date.month).save(path)
    except PermissionError:
        # File is open in Excel; the DB still has the record and the next punch rewrites it.
        pass
    return path


# ---------------------------------------------------------------- analytics

def student_stats(student, days=30):
    """Attendance %, punctuality and a trend-based risk flag over the last `days` days."""
    now = now_local()
    end = now.date()
    start = max(end - dt.timedelta(days=days - 1), timezone.localtime(student.created_at).date())
    batch = student.batch
    recs = {a.date: a for a in student.attendance.filter(date__range=(start, end))}
    records = {(student.id, d): r for d, r in recs.items()}
    scheduled, hits, delays = [], [], []
    d = start
    while d <= end:
        code = day_status(student, batch, d, records, now)
        if code in ("P", "L", "A"):
            scheduled.append(d)
            hits.append(1.0 if code in ("P", "L") else 0.0)
            if d in recs:
                delay = (_combine(d, recs[d].time_in) - _combine(d, student.start_time)).total_seconds() / 60
                delays.append(delay)
        d += dt.timedelta(days=1)

    total = len(scheduled)
    pct = round(100 * sum(hits) / total, 1) if total else None
    late = sum(1 for r in recs.values() if r.status == Attendance.LATE)
    # Trend: slope of a line through the daily 0/1 attendance (per 7 days), via least squares.
    slope = None
    if total >= 4:
        x = np.array([(s - scheduled[0]).days for s in scheduled], dtype=float)
        slope = float(np.polyfit(x, np.array(hits), 1)[0] * 7)
    risk = "low"
    if pct is not None and (pct < 60 or (slope is not None and slope < -0.15 and pct < 85)):
        risk = "high"
    elif pct is not None and (pct < 75 or (slope is not None and slope < -0.05)):
        risk = "medium"
    return {
        "student": student, "scheduled": total, "attended": int(sum(hits)), "late": late,
        "percent": pct, "avg_delay": round(float(np.mean(delays)), 1) if delays else None,
        "trend": round(slope * 100, 1) if slope is not None else None, "risk": risk,
    }


def batch_daily_trend(batch, days=30):
    """Per-day counts for charting: (labels, present, late, absent)."""
    end = now_local().date()
    start = end - dt.timedelta(days=days - 1)
    dates, rows = register_rows(batch, start, end)
    labels, p, l, a = [], [], [], []
    for i, d in enumerate(dates):
        codes = [r["codes"][i] for r in rows]
        if not any(c in ("P", "L", "A") for c in codes):
            continue
        labels.append(d.strftime("%d %b"))
        p.append(codes.count("P"))
        l.append(codes.count("L"))
        a.append(codes.count("A"))
    return labels, p, l, a
