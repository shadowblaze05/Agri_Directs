from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from app.services import face_scanning


class FakeLandmarker:
    def __init__(self, faces):
        self.faces = faces

    def detect(self, image):
        assert image is not None
        return SimpleNamespace(face_landmarks=self.faces)


def _frame_bytes():
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    encoded, buffer = cv2.imencode(".jpg", frame)
    assert encoded
    return buffer.tobytes()


def _face_landmarks(nose_x=0.5):
    landmarks = [SimpleNamespace(x=0.5, y=0.5) for _ in range(468)]
    landmarks[10] = SimpleNamespace(x=0.5, y=0.25)
    landmarks[152] = SimpleNamespace(x=0.5, y=0.75)
    landmarks[234] = SimpleNamespace(x=0.3, y=0.5)
    landmarks[454] = SimpleNamespace(x=0.7, y=0.5)
    landmarks[33] = SimpleNamespace(x=0.42, y=0.43)
    landmarks[263] = SimpleNamespace(x=0.58, y=0.43)
    landmarks[1] = SimpleNamespace(x=nose_x, y=0.55)
    return landmarks


def test_face_scan_accepts_center_and_screen_left_poses(monkeypatch):
    monkeypatch.setattr(
        face_scanning,
        "_get_landmarker",
        lambda: FakeLandmarker([_face_landmarks()]),
    )
    face_scanning.validate_face_frame(_frame_bytes(), "center")

    monkeypatch.setattr(
        face_scanning,
        "_get_landmarker",
        lambda: FakeLandmarker([_face_landmarks(nose_x=0.46)]),
    )
    face_scanning.validate_face_frame(_frame_bytes(), "screen_left")


@pytest.mark.parametrize("faces", [[], [_face_landmarks(), _face_landmarks()]])
def test_face_scan_requires_exactly_one_face(monkeypatch, faces):
    monkeypatch.setattr(
        face_scanning,
        "_get_landmarker",
        lambda: FakeLandmarker(faces),
    )

    with pytest.raises(ValueError, match="exactly one face"):
        face_scanning.validate_face_frame(_frame_bytes(), "center")


def test_face_scan_rejects_pose_that_does_not_match_server_instruction(monkeypatch):
    monkeypatch.setattr(
        face_scanning,
        "_get_landmarker",
        lambda: FakeLandmarker([_face_landmarks()]),
    )

    with pytest.raises(ValueError, match="right edge"):
        face_scanning.validate_face_frame(_frame_bytes(), "screen_right")


def test_face_scan_rejects_corrupted_and_oversized_frames():
    with pytest.raises(ValueError, match="valid image"):
        face_scanning.validate_face_frame(b"not an image", "center")
    with pytest.raises(ValueError, match="too large"):
        face_scanning.validate_face_frame(
            b"x" * (face_scanning.MAX_FRAME_SIZE_BYTES + 1),
            "center",
        )
