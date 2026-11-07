from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("punch/", views.punch, name="punch"),
    path("api/punch/", views.api_punch, name="api_punch"),
    path("signup/", views.student_signup, name="student_signup"),
    path("mentor/signup/", views.mentor_signup, name="mentor_signup"),
    path("mentor/login/", auth_views.LoginView.as_view(), name="login"),
    path("mentor/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("mentor/", views.dashboard, name="dashboard"),
    path("mentor/batches/new/", views.batch_form, name="batch_create"),
    path("mentor/batches/<int:pk>/", views.batch_detail, name="batch_detail"),
    path("mentor/batches/<int:pk>/edit/", views.batch_form, name="batch_edit"),
    path("mentor/batches/<int:pk>/delete/", views.batch_delete, name="batch_delete"),
    path("mentor/batches/<int:pk>/register.xlsx", views.download_register, name="download_register"),
    path("mentor/students/<int:pk>/edit/", views.student_edit, name="student_edit"),
    path("mentor/students/<int:pk>/mark/", views.manual_mark, name="manual_mark"),
    path("lead/", views.lead_overview, name="lead_overview"),
    path("lead/report.xlsx", views.lead_export, name="lead_export"),
]
