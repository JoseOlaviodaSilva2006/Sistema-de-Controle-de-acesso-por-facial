import argparse
import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np


CASCADE_PATH = Path("data") / "haarcascade_frontalface_alt.xml"
DB_PATH = Path("access_control_v2.db")
MODEL_PATH = Path("data") / "lbph_model.yml"
FACE_SIZE = (160, 160)
MIN_FACE_SIZE = (90, 90)
REQUIRED_SAMPLES = 100
CONFIDENCE_THRESHOLD = 95.0
ACCESS_DENIED_SECONDS = 3.0
ACCESS_GRANTED_SECONDS = 3.0
REQUIRED_CONSISTENT_MATCHES = 3
AUTO_UPDATE_MIN_INTERVAL_SECONDS = 20.0
AUTO_RETRAIN_EVERY_NEW_SAMPLES = 10

# Visual identity (BGR)
COLOR_BG = (18, 22, 28)
COLOR_SURFACE = (30, 38, 48)
COLOR_SURFACE_SOFT = (38, 47, 58)
COLOR_PRIMARY = (255, 173, 64)
COLOR_TEXT = (240, 240, 240)
COLOR_TEXT_MUTED = (185, 195, 205)
COLOR_SUCCESS = (72, 191, 117)
COLOR_DANGER = (80, 80, 240)
COLOR_INFO = (145, 205, 255)


@dataclass
class User:
    id: int
    name: str
    active: int = 1


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS face_samples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(user_id) REFERENCES users(id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    event_type TEXT NOT NULL,
                    confidence REAL,
                    details TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert_user(self, name: str) -> User:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, name, active FROM users WHERE name = ? LIMIT 1", (name,)
            ).fetchone()
            if row:
                return User(id=row[0], name=row[1], active=row[2])
            cursor = conn.execute("INSERT INTO users(name) VALUES (?)", (name,))
            return User(id=cursor.lastrowid, name=name, active=1)

    def user_by_id(self, user_id: int) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, name FROM users WHERE id = ? AND active = 1 LIMIT 1", (user_id,)
            ).fetchone()
            if not row:
                return None
            return User(id=row[0], name=row[1], active=1)

    def user_by_id_any(self, user_id: int) -> Optional[User]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, name, active FROM users WHERE id = ? LIMIT 1", (user_id,)
            ).fetchone()
            if not row:
                return None
            return User(id=row[0], name=row[1], active=row[2])

    def list_users(self) -> List[User]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT id, name, active FROM users ORDER BY id"
            ).fetchall()
            return [User(id=r[0], name=r[1], active=r[2]) for r in rows]

    def create_user(self, name: str, active: int = 1) -> User:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "INSERT INTO users(name, active) VALUES (?, ?)",
                (name.strip(), int(active)),
            )
            return User(id=cursor.lastrowid, name=name.strip(), active=int(active))

    def update_user(self, user_id: int, name: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE users SET name = ? WHERE id = ?",
                (name.strip(), user_id),
            )

    def set_user_active(self, user_id: int, active: int) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "UPDATE users SET active = ? WHERE id = ?",
                (int(active), user_id),
            )

    def add_sample(self, user_id: int, image_path: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO face_samples(user_id, image_path) VALUES (?, ?)",
                (user_id, image_path),
            )

    def get_all_samples(self) -> List[Tuple[int, str]]:
        with sqlite3.connect(self.db_path) as conn:
            return conn.execute(
                """
                SELECT fs.user_id, fs.image_path
                FROM face_samples fs
                JOIN users u ON u.id = fs.user_id
                WHERE u.active = 1
                ORDER BY fs.id
                """
            ).fetchall()

    def get_user_samples(self, user_id: int) -> List[str]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                "SELECT image_path FROM face_samples WHERE user_id = ? ORDER BY id DESC",
                (user_id,),
            ).fetchall()
            return [r[0] for r in rows]

    @staticmethod
    def _hash_password(password: str) -> str:
        # PBKDF2-HMAC with static app salt for local desktop use.
        salt = b"facial-auth-v2-admin-salt"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 200_000)
        return digest.hex()

    def ensure_default_admin(self, username: str, password: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT id FROM admins LIMIT 1").fetchone()
            if row:
                return
            conn.execute(
                "INSERT INTO admins(username, password_hash, active) VALUES (?, ?, 1)",
                (username, self._hash_password(password)),
            )

    def verify_admin(self, username: str, password: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT password_hash, active FROM admins WHERE username = ? LIMIT 1",
                (username.strip(),),
            ).fetchone()
            if not row:
                return False
            if int(row[1]) != 1:
                return False
            return self._hash_password(password) == row[0]

    def create_admin(self, username: str, password: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO admins(username, password_hash, active) VALUES (?, ?, 1)",
                (username.strip(), self._hash_password(password)),
            )

    def log_event(
        self,
        event_type: str,
        user_id: Optional[int] = None,
        confidence: Optional[float] = None,
        details: str = "",
    ) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO auth_events(user_id, event_type, confidence, details) VALUES (?, ?, ?, ?)",
                (user_id, event_type, confidence, details),
            )


class FaceEngine:
    def __init__(self, cascade_path: Path, model_path: Path, storage: Storage) -> None:
        if not cascade_path.exists():
            raise FileNotFoundError(
                f"Cascade file not found at {cascade_path}. Ensure OpenCV cascade XML exists."
            )
        self.cascade = cv2.CascadeClassifier(str(cascade_path))
        if self.cascade.empty():
            raise RuntimeError(f"Failed to load cascade from {cascade_path}")

        if not hasattr(cv2, "face") or not hasattr(cv2.face, "LBPHFaceRecognizer_create"):
            raise RuntimeError(
                "OpenCV contrib module not found. Install opencv-contrib-python."
            )
        self.recognizer = cv2.face.LBPHFaceRecognizer_create(radius=2, neighbors=12, grid_x=8, grid_y=8)
        self.model_path = model_path
        self.storage = storage
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        self.model_ready = False
        self.try_load_model()

    def try_load_model(self) -> None:
        if self.model_path.exists():
            self.recognizer.read(str(self.model_path))
            self.model_ready = True

    def detect_primary_face(self, frame: np.ndarray) -> Optional[np.ndarray]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=MIN_FACE_SIZE,
            flags=cv2.CASCADE_SCALE_IMAGE,
        )
        if len(faces) == 0:
            return None
        x, y, w, h = sorted(faces, key=lambda f: f[2] * f[3], reverse=True)[0]
        face = gray[y : y + h, x : x + w]
        face = cv2.resize(face, FACE_SIZE, interpolation=cv2.INTER_AREA)
        # Normalize contrast to reduce lighting sensitivity and improve LBPH stability.
        face = cv2.equalizeHist(face)
        return face

    def train_from_db(self) -> bool:
        samples = self.storage.get_all_samples()
        if not samples:
            self.model_ready = False
            return False

        images: List[np.ndarray] = []
        labels: List[int] = []
        for user_id, image_path in samples:
            if not os.path.exists(image_path):
                continue
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            img = cv2.resize(img, FACE_SIZE, interpolation=cv2.INTER_AREA)
            images.append(img)
            labels.append(user_id)

        if not images:
            self.model_ready = False
            return False

        self.recognizer.train(images, np.array(labels))
        self.recognizer.save(str(self.model_path))
        self.model_ready = True
        return True

    def predict(self, face_gray: np.ndarray) -> Tuple[int, float]:
        if not self.model_ready:
            raise RuntimeError("Model not trained yet.")
        label, confidence = self.recognizer.predict(face_gray)
        return int(label), float(confidence)


def _open_camera(index: int = 0) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        raise RuntimeError("Unable to access camera.")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    return cap


def _draw_panel(frame: np.ndarray, x1: int, y1: int, x2: int, y2: int, color: Tuple[int, int, int], alpha: float) -> None:
    overlay = frame.copy()
    cv2.rectangle(overlay, (x1, y1), (x2, y2), color, -1)
    cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)


def _draw_header(frame: np.ndarray, title: str, subtitle: str) -> None:
    width = frame.shape[1]
    _draw_panel(frame, 0, 0, width, 110, COLOR_BG, 0.72)
    cv2.putText(frame, title, (24, 44), cv2.FONT_HERSHEY_DUPLEX, 1.0, COLOR_TEXT, 2, cv2.LINE_AA)
    cv2.putText(frame, subtitle, (24, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOR_TEXT_MUTED, 2, cv2.LINE_AA)


def _draw_footer(frame: np.ndarray, hint: str) -> None:
    height, width = frame.shape[:2]
    _draw_panel(frame, 0, height - 56, width, height, COLOR_BG, 0.66)
    cv2.putText(frame, hint, (24, height - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.58, COLOR_TEXT_MUTED, 2, cv2.LINE_AA)


def _draw_progress(frame: np.ndarray, saved: int, total: int) -> None:
    width = frame.shape[1]
    _draw_panel(frame, 24, 128, width - 24, 188, COLOR_SURFACE, 0.84)

    percent = 0.0 if total <= 0 else min(1.0, saved / float(total))
    bar_x1, bar_y1, bar_x2, bar_y2 = 40, 160, width - 40, 176
    cv2.rectangle(frame, (bar_x1, bar_y1), (bar_x2, bar_y2), COLOR_SURFACE_SOFT, -1)
    fill_x = int(bar_x1 + (bar_x2 - bar_x1) * percent)
    cv2.rectangle(frame, (bar_x1, bar_y1), (fill_x, bar_y2), COLOR_PRIMARY, -1)

    cv2.putText(
        frame,
        f"Enrollment Progress  {saved}/{total}",
        (40, 150),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        COLOR_TEXT,
        2,
        cv2.LINE_AA,
    )


def _draw_status_badge(frame: np.ndarray, label: str, detail: str, color: Tuple[int, int, int]) -> None:
    width = frame.shape[1]
    _draw_panel(frame, 24, 128, width - 24, 210, COLOR_SURFACE, 0.88)
    cv2.circle(frame, (52, 166), 12, color, -1)
    cv2.putText(frame, label, (78, 172), cv2.FONT_HERSHEY_DUPLEX, 0.9, COLOR_TEXT, 2, cv2.LINE_AA)
    cv2.putText(frame, detail, (78, 198), cv2.FONT_HERSHEY_SIMPLEX, 0.58, COLOR_TEXT_MUTED, 2, cv2.LINE_AA)


def enroll(user_name: str) -> None:
    storage = Storage(DB_PATH)
    user = storage.upsert_user(user_name.strip())
    engine = FaceEngine(CASCADE_PATH, MODEL_PATH, storage)
    samples_dir = Path("data") / "faces" / str(user.id)
    samples_dir.mkdir(parents=True, exist_ok=True)

    cap = _open_camera(0)
    saved = 0

    print(f"Enrolling user '{user.name}' (id={user.id})...")
    print("Look at the camera. Press 'q' to cancel.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue

            frame = cv2.flip(frame, 1)
            face = engine.detect_primary_face(frame)
            if face is not None:
                sample_file = samples_dir / f"{time.time_ns()}.jpg"
                # JPEG reduces disk IO vs PNG and allows faster burst capture.
                cv2.imwrite(str(sample_file), face, [cv2.IMWRITE_JPEG_QUALITY, 88])
                storage.add_sample(user.id, str(sample_file))
                saved += 1

            _draw_header(
                frame,
                "Enrollment",
                f"User: {user.name}  |  Capture consistent angles for best accuracy",
            )
            _draw_progress(frame, saved, REQUIRED_SAMPLES)
            _draw_footer(frame, "Press q to cancel enrollment")
            cv2.imshow("Enrollment", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if saved >= REQUIRED_SAMPLES:
                break

    finally:
        cap.release()
        cv2.destroyAllWindows()

    if saved < REQUIRED_SAMPLES:
        print(f"Enrollment cancelled/incomplete: collected {saved}/{REQUIRED_SAMPLES}")
        storage.log_event("enroll_incomplete", user_id=user.id, details=f"samples={saved}")
        return

    if engine.train_from_db():
        print("Enrollment complete. Model retrained successfully.")
        storage.log_event("enroll_success", user_id=user.id, details=f"samples={saved}")
    else:
        print("Enrollment saved, but model training failed.")
        storage.log_event("enroll_training_failed", user_id=user.id, details=f"samples={saved}")


def verify() -> None:
    storage = Storage(DB_PATH)
    engine = FaceEngine(CASCADE_PATH, MODEL_PATH, storage)

    if not engine.model_ready:
        retrained = engine.train_from_db()
        if not retrained:
            raise RuntimeError("No trained model and no samples found. Enroll users first.")

    cap = _open_camera(0)
    denied_until = 0.0
    granted_until = 0.0
    granted_user_name = ""
    granted_confidence = 0.0
    consecutive_match_count = 0
    last_matched_user_id: Optional[int] = None
    last_auto_update_at: dict[int, float] = {}
    pending_auto_samples = 0

    print("Verification started. Press 'q' to quit.")

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                continue
            frame = cv2.flip(frame, 1)
            now = time.time()

            status_text = "Scanning..."
            status_color = COLOR_INFO
            status_detail = "Align your face inside the camera view"

            if now < granted_until:
                status_text = f"Access Granted: {granted_user_name}"
                status_color = COLOR_SUCCESS
                remaining = max(0.0, granted_until - now)
                status_detail = (
                    f"Verified successfully ({granted_confidence:.1f}). "
                    f"Returning to scan in {remaining:.1f}s"
                )
            elif now < denied_until:
                # Non-blocking denial window: camera loop keeps running while showing denial status.
                status_text = "Access Denied"
                status_color = COLOR_DANGER
                remaining = max(0.0, denied_until - now)
                status_detail = f"Validation failed. Resuming scan in {remaining:.1f}s"
            else:
                face = engine.detect_primary_face(frame)
                if face is not None:
                    label, confidence = engine.predict(face)
                    user_any = storage.user_by_id_any(label)
                    user = user_any if user_any and user_any.active == 1 else None

                    if user_any and confidence <= CONFIDENCE_THRESHOLD:
                        if last_matched_user_id == user_any.id:
                            consecutive_match_count += 1
                        else:
                            last_matched_user_id = user_any.id
                            consecutive_match_count = 1

                        if consecutive_match_count >= REQUIRED_CONSISTENT_MATCHES:
                            # Keep user profile updated with real verification captures.
                            user_samples_dir = Path("data") / "faces" / str(user_any.id)
                            user_samples_dir.mkdir(parents=True, exist_ok=True)
                            last_update = last_auto_update_at.get(user_any.id, 0.0)
                            if now - last_update >= AUTO_UPDATE_MIN_INTERVAL_SECONDS:
                                auto_sample_file = user_samples_dir / f"verify_{time.time_ns()}.jpg"
                                cv2.imwrite(
                                    str(auto_sample_file),
                                    face,
                                    [cv2.IMWRITE_JPEG_QUALITY, 90],
                                )
                                storage.add_sample(user_any.id, str(auto_sample_file))
                                last_auto_update_at[user_any.id] = now
                                pending_auto_samples += 1
                                # Retrain periodically to avoid heavy cost every single success.
                                if pending_auto_samples >= AUTO_RETRAIN_EVERY_NEW_SAMPLES:
                                    if engine.train_from_db():
                                        pending_auto_samples = 0

                            if user and user.active == 1:
                                status_text = f"Access Granted: {user.name}"
                                status_color = COLOR_SUCCESS
                                status_detail = f"Verified ({confidence:.1f}) with stable multi-frame match"
                                granted_user_name = user.name
                                granted_confidence = confidence
                                granted_until = now + ACCESS_GRANTED_SECONDS
                                storage.log_event(
                                    "verify_granted",
                                    user_id=user.id,
                                    confidence=confidence,
                                    details=f"lbph_stable_match_{consecutive_match_count}_auto_update",
                                )
                            else:
                                status_text = "Access Denied"
                                status_color = COLOR_DANGER
                                status_detail = (
                                    f"User inactive ({user_any.name}) - updates saved, access blocked"
                                )
                                denied_until = now + ACCESS_DENIED_SECONDS
                                storage.log_event(
                                    "verify_denied_inactive",
                                    user_id=user_any.id,
                                    confidence=confidence,
                                    details="matched_but_inactive_auto_updated",
                                )
                            consecutive_match_count = 0
                            last_matched_user_id = None
                        else:
                            status_text = "Validating..."
                            status_color = COLOR_INFO
                            status_detail = (
                                f"Potential match {user_any.name} ({confidence:.1f}) "
                                f"[{consecutive_match_count}/{REQUIRED_CONSISTENT_MATCHES}]"
                            )
                    else:
                        status_text = "Access Denied"
                        status_color = COLOR_DANGER
                        status_detail = f"Not recognized or low confidence (score={confidence:.1f})"
                        denied_until = now + ACCESS_DENIED_SECONDS
                        consecutive_match_count = 0
                        last_matched_user_id = None
                        storage.log_event(
                            "verify_denied",
                            user_id=label if user else None,
                            confidence=confidence,
                            details="threshold_or_unknown",
                        )

            _draw_header(frame, "Facial Verification", "Real-time access control pipeline")
            _draw_status_badge(frame, status_text, status_detail, status_color)
            _draw_footer(frame, "Press q to quit")
            cv2.imshow("Facial Verification", frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Facial authentication v2 (upgraded, non-blocking verification pipeline)."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    enroll_cmd = sub.add_parser("enroll", help="Enroll a user face profile")
    enroll_cmd.add_argument("--name", required=True, help="Unique display name")

    sub.add_parser("verify", help="Start live verification")
    sub.add_parser("retrain", help="Retrain model from stored samples")

    args = parser.parse_args()
    if args.cmd == "enroll":
        enroll(args.name)
    elif args.cmd == "verify":
        verify()
    elif args.cmd == "retrain":
        storage = Storage(DB_PATH)
        engine = FaceEngine(CASCADE_PATH, MODEL_PATH, storage)
        if engine.train_from_db():
            print("Model retrained.")
        else:
            print("No samples found to retrain.")


if __name__ == "__main__":
    main()
