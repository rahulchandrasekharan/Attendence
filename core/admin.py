from django.contrib import admin

from .models import Attendance, Batch, Student, StudentPhoto


@admin.register(Batch)
class BatchAdmin(admin.ModelAdmin):
    list_display = ("name", "mentor", "start_time", "end_time", "days", "is_active")
    list_filter = ("mentor", "is_active")


class PhotoInline(admin.TabularInline):
    model = StudentPhoto
    extra = 0


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("full_name", "student_id", "batch", "custom_start_time", "custom_end_time", "is_active")
    list_filter = ("batch", "is_active")
    search_fields = ("full_name", "student_id", "email")
    exclude = ("face_embeddings",)
    inlines = [PhotoInline]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ("date", "time_in", "student", "batch", "status", "method", "confidence")
    list_filter = ("date", "batch", "status", "method")
    search_fields = ("student__full_name", "student__student_id")
