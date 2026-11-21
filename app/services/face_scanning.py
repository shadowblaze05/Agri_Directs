"""Transient face-position checks for profile-photo scan challenges."""

import threading
from io import BytesIO
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from flask import current_app
from PIL import Image, UnidentifiedImageError


MAX_FRAME_SIZE_BYTES = 2 * 1024 * 1024
MAX_FRAME_WIDTH = 1920
MAX_FRAME_HEIGHT = 1080
MAX_FRAME_PIXELS = MAX_FRAME_WIDTH * MAX_FRAME_HEIGHT
MAX_SCAN_ATTEMPTS = 5

_LANDMARKER = None
_LANDMARKER_PATH = None
_LANDMARKER_LOCK = threading.Lock()
_DETECTION_LOCK = threading.Lock()
_FACE_POINTS = (33, 263, 1)


class FaceScannerUnavailable(RuntimeError):
    """Raised when the configured face-landmarker model cannot be loaded."""


def _model_path():
    configured_path = current_app.config.get("FACE_LANDMARKER_MODEL_PATH")
    if configured_path:
        return Path(configured_path)
    return Path(__file__).resolve().parents[1] / "static" / "models" / "face_landmarker.task"


def _get_landmarker():
    global _LANDMARKER, _LANDMARKER_PATH

    model_path = _model_path()
    if not model_path.is_file():
        raise FaceScannerUnavailable(
            "The face-scanning model is missing from the server."
        )

    with _LANDMARKER_LOCK:
        if _LANDMARKER is None or _LANDMARKER_PATH != model_path:
            try:
                options = mp.tasks.vision.FaceLandmarkerOptions(
                    base_options=mp.tasks.BaseOptions(
                        model_asset_path=str(model_path)
                    ),
                    running_mode=mp.tasks.vision.RunningMode.IMAGE,
                    num_faces=2,
                )
                _LANDMARKER = mp.tasks.vision.FaceLandmarker.create_from_options(
                    options
                )
                _LANDMARKER_PATH = model_path
            except (OSError, RuntimeError, ValueError) as error:
                raise FaceScannerUnavailable(
                    "The face-scanning model could not be loaded."
                ) from error
        return _LANDMARKER


def ensure_face_scanner_ready():
    """Load the scanner before issuing a challenge so setup errors are explicit."""
    _get_landmarker()


def validate_face_frame(image_bytes, expected_movement):
    """Validate one transient frame against a server-selected face pose."""
    if not isinstance(image_bytes, bytes) or not image_bytes:
        raise ValueError("Capture a clear camera frame and try again.")
    if len(image_bytes) > MAX_FRAME_SIZE_BYTES:
        raise ValueError("The scan frame is too large. Try again.")

    try:
        with Image.open(BytesIO(image_bytes)) as source_image:
            if source_image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use a JPEG, PNG, or WEBP camera frame.")
            if (
                source_image.width * source_image.height > MAX_FRAME_PIXELS
                or source_image.width > MAX_FRAME_WIDTH
                or source_image.height > MAX_FRAME_HEIGHT
            ):
                raise ValueError("The scan frame dimensions are outside the allowed range.")
            source_image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as error:
        raise ValueError("The camera did not provide a valid image frame.") from error

    encoded = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("The camera did not provide a valid image frame.")

    height, width = image.shape[:2]
    if (
        width < 160
        or height < 160
        or width > MAX_FRAME_WIDTH
        or height > MAX_FRAME_HEIGHT
        or width * height > MAX_FRAME_PIXELS
    ):
        raise ValueError("The scan frame dimensions are outside the allowed range.")

    rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    media_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=rgb_image,
    )
    with _DETECTION_LOCK:
        result = _get_landmarker().detect(media_image)

    faces = result.face_landmarks
    if len(faces) != 1:
        raise ValueError("Show exactly one face in the camera preview.")

    landmarks = faces[0]
    if len(landmarks) <= max(_FACE_POINTS):
        raise ValueError("The face could not be clearly detected. Adjust the camera and retry.")

    x_values = [point.x for point in landmarks]
    y_values = [point.y for point in landmarks]
    face_left, face_right = min(x_values), max(x_values)
    face_top, face_bottom = min(y_values), max(y_values)
    face_width = face_right - face_left
    face_height = face_bottom - face_top
    face_center_x = (face_left + face_right) / 2
    face_center_y = (face_top + face_bottom) / 2
    if (
        face_width < 0.18
        or face_width > 0.85
        or face_height < 0.2
        or face_height > 0.9
        or not 0.25 <= face_center_x <= 0.75
        or not 0.15 <= face_center_y <= 0.85
    ):
        raise ValueError("Move your face into the center of the camera preview.")

    left_eye, right_eye, nose = (landmarks[index] for index in _FACE_POINTS)
    eye_span = abs(right_eye.x - left_eye.x)
    if eye_span < 0.08:
        raise ValueError("Face the camera and move closer before continuing.")
    horizontal_pose = (nose.x - (left_eye.x + right_eye.x) / 2) / eye_span

    if expected_movement == "center":
        pose_valid = abs(horizontal_pose) <= 0.12
    elif expected_movement == "screen_left":
        pose_valid = horizontal_pose <= -0.16
    elif expected_movement == "screen_right":
        pose_valid = horizontal_pose >= 0.16
    else:
        raise ValueError("The requested scan movement is invalid.")

    if not pose_valid:
        movement_text = {
            "center": "Face the camera straight on.",
            "screen_left": "Turn slightly so your nose moves toward the left edge of the screen.",
            "screen_right": "Turn slightly so your nose moves toward the right edge of the screen.",
        }[expected_movement]
        raise ValueError(movement_text)
