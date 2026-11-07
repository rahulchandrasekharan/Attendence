# FaceAttend: face recognition attendance for training batches

Students sign up with their details and 3 or more face photos. At class time they punch in at the
webcam. The app recognises the face, checks the student's batch timing for today's date and marks
**Present** or **Late**. Every punch is saved in the database and in a monthly Excel register per batch.

## Run

```bash
venv\Scripts\python manage.py runserver 8010
```

Open http://localhost:8010. `python manage.py seed_demo` creates these demo accounts. Change the passwords after logging in.

| Login | Role | Sees |
|---|---|---|
| `rahul` / `mentor123` | Trainer: Batch 1 (9-11), Batch 2 (11-1), Batch 3 (2-4) | Only his own batches and students |
| `priya` / `mentor123` | Trainer: Morning DS, Evening DS | Only her own batches and students |
| `lead` / `lead123` | Team lead | **Team overview** (`/lead/`): every trainer, filters by trainer, batch, risk, period and search, Excel export. Can open any batch read-only. |

## Roles

- **Trainer (mentor):** any account created at *Mentor sign up*. Sees and edits only their own batches and students.
  Other trainers' pages return 404.
- **Team lead:** a member of the `Team Lead` group, or a superuser. Grant or remove access with
  `python manage.py set_team_lead <username>` / `python manage.py set_team_lead <username> --remove`, or in `/admin/`.
  A team lead can still have batches of their own, which they can edit as normal.

Fresh install: `python -m venv venv`, `venv\Scripts\pip install -r requirements.txt`,
`venv\Scripts\python manage.py migrate`. The ONNX models in `ml_models/` come from the OpenCV model zoo
(face_detection_yunet_2023mar.onnx, face_recognition_sface_2021dec.onnx).

## How it works

| Piece | Where |
|---|---|
| Face detection (YuNet) + 128-d embeddings (SFace), cosine matching | `core/face_engine.py` |
| Punch rules: class day, window opens 15 min before start, Late after 10 min, closes at end, one punch per day | `core/services.py` → `check_window`, `punch_in` |
| Per-student timing override (a mentor moves one student's slot) | `Student.custom_start_time / custom_end_time` |
| Excel register `attendance_files/<mentor>/<batch>_<YYYY-MM>.xlsx` (P/L/A matrix + punch log), rebuilt after every punch | `services.write_register` |
| Analytics: attendance %, average arrival delay, least-squares trend slope, risk flag | `services.student_stats` |

Tune these in `attendance_ai/settings.py`: `FACE_MATCH_THRESHOLD` (0.40), `PUNCH_OPEN_BEFORE_MIN` (15)
and `LATE_AFTER_MIN` (10).

Notes
- Browsers allow the webcam only on `localhost` or HTTPS. A kiosk tablet on the LAN needs HTTPS.
- There is no liveness check yet, so a printed photo of a student could be used to punch in.
