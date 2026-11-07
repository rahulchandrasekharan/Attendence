import numpy as np
from django.conf import settings
from django.db import models

WEEKDAYS = [(0, "Mon"), (1, "Tue"), (2, "Wed"), (3, "Thu"), (4, "Fri"), (5, "Sat"), (6, "Sun")]


class Batch(models.Model):
    """A training batch owned by a mentor, e.g. 'Batch 1' 09:00-11:00."""

    mentor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="batches")
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    # Comma separated weekday numbers (0=Mon ... 6=Sun) on which the batch runs.
    days = models.CharField(max_length=20, default="0,1,2,3,4,5")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["start_time"]
        unique_together = [("mentor", "name")]

    def __str__(self):
        return f"{self.name} ({self.start_time:%H:%M}-{self.end_time:%H:%M})"

    @property
    def day_list(self):
        return [int(d) for d in self.days.split(",") if d.strip() != ""]

    @property
    def day_labels(self):
        names = dict(WEEKDAYS)
        return ", ".join(names[d] for d in self.day_list)

    def runs_on(self, date):
        return date.weekday() in self.day_list


class Student(models.Model):
    full_name = models.CharField(max_length=120)
    student_id = models.CharField("Student / roll ID", max_length=40, unique=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="students")
    # Optional per-student timing override (when a mentor moves one student's slot).
    custom_start_time = models.TimeField(null=True, blank=True)
    custom_end_time = models.TimeField(null=True, blank=True)
    # float32 array of shape (n_photos, 128), one SFace embedding per enrolled photo.
    face_embeddings = models.BinaryField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["full_name"]

    def __str__(self):
        return f"{self.full_name} ({self.student_id})"

    @property
    def start_time(self):
        return self.custom_start_time or self.batch.start_time

    @property
    def end_time(self):
        return self.custom_end_time or self.batch.end_time

    @property
    def has_custom_timing(self):
        return bool(self.custom_start_time or self.custom_end_time)

    def get_embeddings(self):
        return np.frombuffer(bytes(self.face_embeddings), dtype=np.float32).reshape(-1, 128)

    def set_embeddings(self, arr):
        self.face_embeddings = np.asarray(arr, dtype=np.float32).reshape(-1, 128).tobytes()


class StudentPhoto(models.Model):
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="photos")
    image = models.ImageField(upload_to="enroll/")
    created_at = models.DateTimeField(auto_now_add=True)


class Attendance(models.Model):
    PRESENT = "P"
    LATE = "L"
    STATUS_CHOICES = [(PRESENT, "Present"), (LATE, "Late")]
    METHOD_CHOICES = [("face", "Face"), ("manual", "Manual (mentor)")]

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="attendance")
    # Batch at the time of punching, so history stays correct if the student moves batch later.
    batch = models.ForeignKey(Batch, on_delete=models.CASCADE, related_name="attendance")
    date = models.DateField()
    time_in = models.TimeField()
    status = models.CharField(max_length=1, choices=STATUS_CHOICES)
    confidence = models.FloatField(null=True, blank=True)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default="face")
    snapshot = models.ImageField(upload_to="punches/%Y/%m/%d/", null=True, blank=True)

    class Meta:
        ordering = ["-date", "-time_in"]
        unique_together = [("student", "date")]

    def __str__(self):
        return f"{self.student} {self.date} {self.get_status_display()}"
