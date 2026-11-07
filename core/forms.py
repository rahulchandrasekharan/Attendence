from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import WEEKDAYS, Batch, Student

TIME = forms.TimeInput(attrs={"type": "time"}, format="%H:%M")


class MentorSignupForm(UserCreationForm):
    first_name = forms.CharField(max_length=60)
    last_name = forms.CharField(max_length=60, required=False)
    email = forms.EmailField(required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")


class BatchForm(forms.ModelForm):
    days = forms.TypedMultipleChoiceField(choices=WEEKDAYS, coerce=int, widget=forms.CheckboxSelectMultiple,
                                          initial=[0, 1, 2, 3, 4, 5])

    class Meta:
        model = Batch
        fields = ["name", "start_time", "end_time", "days", "is_active"]
        widgets = {"start_time": TIME, "end_time": TIME}

    def __init__(self, *args, mentor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.mentor = mentor
        if self.instance.pk:
            self.initial["days"] = self.instance.day_list

    def clean(self):
        data = super().clean()
        s, e = data.get("start_time"), data.get("end_time")
        if s and e and e <= s:
            self.add_error("end_time", "End time must be after start time.")
        name = data.get("name")
        if name and Batch.objects.filter(mentor=self.mentor, name__iexact=name).exclude(pk=self.instance.pk).exists():
            self.add_error("name", "You already have a batch with this name.")
        return data

    def clean_days(self):
        days = self.cleaned_data["days"]
        if not days:
            raise forms.ValidationError("Pick at least one day.")
        return ",".join(str(d) for d in sorted(days))


class BatchChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, b):
        mentor = b.mentor.get_full_name() or b.mentor.username
        return f"{b.name}  ·  {b.start_time:%I:%M %p}-{b.end_time:%I:%M %p}  ·  Mentor {mentor}"


class StudentSignupForm(forms.ModelForm):
    batch = BatchChoiceField(queryset=Batch.objects.filter(is_active=True).select_related("mentor"))

    class Meta:
        model = Student
        fields = ["full_name", "student_id", "email", "phone", "batch"]


class StudentEditForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = ["full_name", "email", "phone", "batch", "custom_start_time", "custom_end_time", "is_active"]
        widgets = {"custom_start_time": TIME, "custom_end_time": TIME}
        help_texts = {
            "custom_start_time": "Leave empty to use the batch timing.",
            "custom_end_time": "Leave empty to use the batch timing.",
        }

    def __init__(self, *args, mentor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["batch"] = BatchChoiceField(queryset=Batch.objects.filter(mentor=mentor))

    def clean(self):
        data = super().clean()
        batch = data.get("batch")
        s = data.get("custom_start_time") or (batch.start_time if batch else None)
        e = data.get("custom_end_time") or (batch.end_time if batch else None)
        if s and e and e <= s:
            self.add_error("custom_end_time", "End time must be after start time.")
        return data
