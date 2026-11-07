"""Face detection + recognition using OpenCV's YuNet (detector) and SFace (128-d embeddings).

Both are small ONNX models from the OpenCV model zoo, so no dlib / TensorFlow is needed.
"""
import base64
import threading

import cv2
import numpy as np
from django.conf import settings

_lock = threading.Lock()
_detector = None
_recognizer = None


class FaceError(Exception):
    """A user-facing problem with a photo (no face, several faces, unreadable image)."""


def _models():
    global _detector, _recognizer
    if _detector is None:
        model_dir = settings.ML_MODELS_DIR
        _detector = cv2.FaceDetectorYN.create(
            str(model_dir / "face_detection_yunet_2023mar.onnx"), "", (320, 320),
            score_threshold=0.8, nms_threshold=0.3, top_k=50,
        )
        _recognizer = cv2.FaceRecognizerSF.create(str(model_dir / "face_recognition_sface_2021dec.onnx"), "")
    return _detector, _recognizer


def decode_image(data):
    """Accept raw bytes or a 'data:image/...;base64,' string and return a BGR image."""
    if isinstance(data, str):
        if "," in data:
            data = data.split(",", 1)[1]
        data = base64.b64decode(data)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise FaceError("Could not read the image.")
    # Keep detection fast and consistent for large phone photos.
    h, w = img.shape[:2]
    scale = 960 / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (int(w * scale), int(h * scale)))
    return img


def detect_faces(img):
    detector, _ = _models()
    h, w = img.shape[:2]
    with _lock:
        detector.setInputSize((w, h))
        _, faces = detector.detect(img)
    return [] if faces is None else list(faces)


def embed(img, require_single=True):
    """Return (embedding[128], face_box) for the main face in the image."""
    faces = detect_faces(img)
    if not faces:
        raise FaceError("No face detected. Face the camera in good light.")
    if require_single and len(faces) > 1:
        raise FaceError("More than one face detected. Only one person should be in the frame.")
    # Largest face wins (the person standing closest to the kiosk).
    face = max(faces, key=lambda f: f[2] * f[3])
    if face[2] < 60 or face[3] < 60:
        raise FaceError("Face is too small. Move closer to the camera.")
    _, recognizer = _models()
    with _lock:
        aligned = recognizer.alignCrop(img, face)
        feat = recognizer.feature(aligned).flatten().astype(np.float32)
    feat /= np.linalg.norm(feat) + 1e-9
    return feat, face


def best_match(embedding, students):
    """Compare against each student's enrolled embeddings (cosine similarity).

    Returns (student, score) for the best student, or (None, best_score) if below threshold.
    """
    best_student, best_score = None, -1.0
    for student in students:
        enrolled = student.get_embeddings()
        if enrolled.size == 0:
            continue
        score = float(np.max(enrolled @ embedding))
        if score > best_score:
            best_student, best_score = student, score
    if best_score < settings.FACE_MATCH_THRESHOLD:
        return None, best_score
    return best_student, best_score


def crop_jpeg(img, face, pad=0.35):
    """JPEG bytes of the face region (for the punch-in snapshot)."""
    x, y, w, h = [int(v) for v in face[:4]]
    px, py = int(w * pad), int(h * pad)
    H, W = img.shape[:2]
    crop = img[max(0, y - py):min(H, y + h + py), max(0, x - px):min(W, x + w + px)]
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return buf.tobytes() if ok else None
