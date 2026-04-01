import argparse
import hashlib
import os
import sqlite3
import time
import datetime
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import cv2
import numpy as np
import pytz
from secure_storage import secure_io

# Configuração de Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AuraAuth")

def get_br_time():
    return datetime.datetime.now(pytz.timezone('America/Sao_Paulo')).strftime('%Y-%m-%d %H:%M:%S')

def load_env():
    """Carregador simples de .env para evitar dependências extras se possível."""
    env = {}
    env_path = Path(".env")
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip()
    return env

_cfg = load_env()

# --- CONSTANTES CONFIGURÁVEIS ---
CASCADE_PATH = Path(_cfg.get("CASCADE_PATH", "data/haarcascade_frontalface_alt.xml"))
DB_PATH = Path(_cfg.get("DB_PATH", "access_control_v2.db"))
MODEL_PATH = Path(_cfg.get("MODEL_PATH", "data/lbph_model.yml"))
FACE_SIZE = (160, 160)
MIN_FACE_SIZE = (90, 90)
REQUIRED_SAMPLES = int(_cfg.get("REQUIRED_SAMPLES", 100))
CONFIDENCE_THRESHOLD = float(_cfg.get("CONFIDENCE_THRESHOLD", 95.0))
ACCESS_DENIED_SECONDS = 3.0
ACCESS_GRANTED_SECONDS = 3.0
REQUIRED_CONSISTENT_MATCHES = int(_cfg.get("REQUIRED_CONSISTENT_MATCHES", 3))

# Cores Aura (BGR)
COLOR_SUCCESS = (117, 191, 72)
COLOR_DANGER = (80, 80, 240)
COLOR_INFO = (255, 173, 64)
COLOR_PRIMARY = (64, 173, 255)

@dataclass
class User:
    id: int
    name: str
    active: int = 1
    created_at: str = ""
    cpf: str = ""
    email: str = ""
    phone: str = ""
    dependents: str = ""

class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        try:
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._init_db()
        except sqlite3.Error as e:
            logger.error(f"Erro ao conectar ao banco de dados: {e}")
            raise

    def _init_db(self) -> None:
        try:
            with self.conn:
                self.conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, cpf TEXT DEFAULT '', email TEXT DEFAULT '', phone TEXT DEFAULT '', dependents TEXT DEFAULT '')")
                
                cursor = self.conn.execute("PRAGMA table_info(users)")
                cols = [row[1] for row in cursor.fetchall()]
                if "cpf" not in cols: self.conn.execute("ALTER TABLE users ADD COLUMN cpf TEXT DEFAULT ''")
                if "email" not in cols: self.conn.execute("ALTER TABLE users ADD COLUMN email TEXT DEFAULT ''")
                if "phone" not in cols: self.conn.execute("ALTER TABLE users ADD COLUMN phone TEXT DEFAULT ''")
                if "dependents" not in cols: self.conn.execute("ALTER TABLE users ADD COLUMN dependents TEXT DEFAULT ''")
                
                # Check for unique index on cpf
                idx_cursor = self.conn.execute("PRAGMA index_list(users)")
                indexes = [row[1] for row in idx_cursor.fetchall()]
                if "idx_users_cpf" not in indexes:
                    # Ignore empty cpfs for uniqueness
                    self.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_cpf ON users(cpf) WHERE cpf != ''")
                
                self.conn.execute("CREATE TABLE IF NOT EXISTS dependents (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, name TEXT NOT NULL, cpf TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))")
                
                self.conn.execute("CREATE TABLE IF NOT EXISTS face_samples (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, image_path TEXT NOT NULL, created_at TEXT NOT NULL, FOREIGN KEY(user_id) REFERENCES users(id))")
                
                self.conn.execute("CREATE TABLE IF NOT EXISTS auth_events (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, event_type TEXT NOT NULL, confidence REAL, created_at TEXT NOT NULL, image_path TEXT DEFAULT '')")
                
                # Migração: Adicionar coluna 'image_path' em auth_events
                cursor = self.conn.execute("PRAGMA table_info(auth_events)")
                cols = [row[1] for row in cursor.fetchall()]
                if "image_path" not in cols:
                    self.conn.execute("ALTER TABLE auth_events ADD COLUMN image_path TEXT DEFAULT ''")
                
                self.conn.execute("CREATE TABLE IF NOT EXISTS admins (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, salt TEXT, active INTEGER NOT NULL DEFAULT 1)")
                
                cursor = self.conn.execute("PRAGMA table_info(admins)")
                cols = [row[1] for row in cursor.fetchall()]
                if "salt" not in cols:
                    self.conn.execute("ALTER TABLE admins ADD COLUMN salt TEXT")
        except sqlite3.Error as e:
            logger.error(f"Erro ao inicializar tabelas: {e}")

    def __del__(self):
        try: 
            if hasattr(self, 'conn'): self.conn.close()
        except Exception: pass

    def list_users(self) -> List[User]:
        try:
            rows = self.conn.execute("SELECT id, name, active, created_at, cpf, email, phone, dependents FROM users ORDER BY id DESC").fetchall()
            return [User(id=r[0], name=r[1], active=r[2], created_at=r[3], cpf=r[4], email=r[5], phone=r[6], dependents=r[7]) for r in rows]
        except sqlite3.Error as e:
            logger.error(f"Erro ao listar usuários: {e}")
            return []

    def create_user(self, name: str, cpf: str = "", email: str = "", phone: str = "", dependents: str = "") -> User:
        clean_name = "".join([c for c in name.strip() if c.isalnum() or c in (" ", "-", "_")])
        if not clean_name: raise ValueError("Nome de usuário contém apenas caracteres proibidos ou está vazio.")
        
        try:
            with self.conn:
                cursor = self.conn.execute("INSERT INTO users(name, cpf, email, phone, dependents, created_at) VALUES (?, ?, ?, ?, ?, ?)", (clean_name, cpf, email, phone, dependents, get_br_time()))
                return User(id=cursor.lastrowid, name=clean_name, cpf=cpf, email=email, phone=phone, dependents=dependents)
        except sqlite3.IntegrityError as e:
            if "cpf" in str(e).lower():
                raise ValueError(f"O CPF '{cpf}' já está cadastrado no sistema.")
            raise ValueError(f"O usuário '{clean_name}' já existe.")
        except sqlite3.Error as e:
            logger.error(f"Erro ao criar usuário: {e}")
            raise

    def update_user(self, user_id: int, updates: dict) -> None:
        try:
            with self.conn:
                if "name" in updates:
                    clean_name = "".join([c for c in updates["name"].strip() if c.isalnum() or c in (" ", "-", "_")])
                    if not clean_name: raise ValueError("Nome inválido.")
                    updates["name"] = clean_name
                    
                fields = ", ".join([f"{k} = ?" for k in updates.keys()])
                values = list(updates.values())
                values.append(user_id)
                self.conn.execute(f"UPDATE users SET {fields} WHERE id = ?", tuple(values))
        except sqlite3.IntegrityError as e:
            if "cpf" in str(e).lower():
                raise ValueError("Este CPF já está sendo utilizado por outro usuário.")
            raise ValueError("O novo nome já existe no sistema.")
        except sqlite3.Error as e:
            logger.error(f"Erro ao atualizar usuário: {e}")
            raise

    def set_user_active(self, user_id: int, active: int) -> None:
        try:
            with self.conn:
                self.conn.execute("UPDATE users SET active = ? WHERE id = ?", (active, user_id))
        except sqlite3.Error as e:
            logger.error(f"Erro ao atualizar status do usuário: {e}")

    def delete_user(self, user_id: int) -> None:
        try:
            paths = self.conn.execute("SELECT image_path FROM face_samples WHERE user_id = ?", (user_id,)).fetchall()
            dep_paths = self.conn.execute("SELECT id FROM dependents WHERE user_id = ?", (user_id,)).fetchall()
            with self.conn:
                self.conn.execute("DELETE FROM face_samples WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM dependents WHERE user_id = ?", (user_id,))
                self.conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            
            for (p,) in paths:
                if os.path.exists(p): os.remove(p)
            
            for (d_id,) in dep_paths:
                d_dir = Path(f"data/dependents/{d_id}")
                if d_dir.exists():
                    import shutil
                    shutil.rmtree(d_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Erro ao deletar usuário: {e}")

    def add_dependent(self, user_id: int, name: str, cpf: str) -> int:
        try:
            with self.conn:
                cursor = self.conn.execute("INSERT INTO dependents(user_id, name, cpf, created_at) VALUES (?, ?, ?, ?)", (user_id, name, cpf, get_br_time()))
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"O CPF '{cpf}' já está registrado.")
        except sqlite3.Error as e:
            logger.error(f"Erro ao criar dependente: {e}")
            raise

    def get_dependents(self, user_id: int) -> List[dict]:
        try:
            rows = self.conn.execute("SELECT id, name, cpf FROM dependents WHERE user_id = ?", (user_id,)).fetchall()
            return [{"id": r[0], "name": r[1], "cpf": r[2]} for r in rows]
        except sqlite3.Error: return []

    def add_sample(self, user_id: int, image_path: str) -> None:
        try:
            with self.conn:
                self.conn.execute("INSERT INTO face_samples(user_id, image_path, created_at) VALUES (?, ?, ?)", (user_id, image_path, get_br_time()))
                
                rows = self.conn.execute("SELECT id, image_path FROM face_samples WHERE user_id = ? ORDER BY id ASC", (user_id,)).fetchall()
                if len(rows) > REQUIRED_SAMPLES:
                    to_delete = rows[:len(rows) - REQUIRED_SAMPLES]
                    for sample_id, path in to_delete:
                        if os.path.exists(path):
                            try: os.remove(path)
                            except OSError: pass
                        self.conn.execute("DELETE FROM face_samples WHERE id = ?", (sample_id,))
        except sqlite3.Error as e:
            logger.error(f"Erro ao gerenciar amostras: {e}")

    def get_all_samples(self) -> List[Tuple[int, str]]:
        try:
            return self.conn.execute("SELECT fs.user_id, fs.image_path FROM face_samples fs JOIN users u ON u.id = fs.user_id WHERE u.active = 1").fetchall()
        except sqlite3.Error: return []

    def user_by_id(self, uid):
        try:
            row = self.conn.execute("SELECT id, name, active FROM users WHERE id = ?", (uid,)).fetchone()
            return User(id=row[0], name=row[1], active=row[2]) if row else None
        except sqlite3.Error: return None

    def log_event(self, event_type: str, user_id: Optional[int] = None, confidence: Optional[float] = None, details: str = "", image_path: str = "") -> None:
        try:
            with self.conn:
                if details:
                    event_type = f"{event_type} - {details}"
                self.conn.execute("INSERT INTO auth_events(user_id, event_type, confidence, created_at, image_path) VALUES (?, ?, ?, ?, ?)", (user_id, event_type, confidence, get_br_time(), image_path))
        except sqlite3.Error as e:
            logger.warning(f"Falha ao registrar log no banco: {e}")

    def get_logs(self) -> List[dict]:
        try:
            rows = self.conn.execute("SELECT e.id, e.event_type, u.name, e.confidence, e.created_at, e.image_path, e.user_id FROM auth_events e LEFT JOIN users u ON e.user_id = u.id ORDER BY e.id DESC").fetchall()
            return [{"id": r[0], "type": r[1], "user": r[2] or "---", "conf": r[3] or 0.0, "time": r[4], "image_path": r[5], "user_id": r[6]} for r in rows]
        except sqlite3.Error: return []

    def _hash(self, password: str, salt: Optional[str] = None) -> Tuple[str, str]:
        if salt is None:
            salt_bytes = os.urandom(16)
        else:
            try: salt_bytes = bytes.fromhex(salt)
            except ValueError: salt_bytes = os.urandom(16) # Fallback seguro
            
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 200_000)
        return digest.hex(), salt_bytes.hex()
    
    def verify_admin(self, u, p):
        try:
            row = self.conn.execute("SELECT password_hash, salt FROM admins WHERE username = ? AND active = 1", (u.strip(),)).fetchone()
            if not row: return False
            
            stored_hash, stored_salt = row
            if not stored_salt:
                old_salt = b"facial-auth-v2-admin-salt"
                old_digest = hashlib.pbkdf2_hmac("sha256", p.encode("utf-8"), old_salt, 200_000).hex()
                if old_digest == stored_hash:
                    new_h, new_s = self._hash(p)
                    with self.conn:
                        self.conn.execute("UPDATE admins SET password_hash = ?, salt = ? WHERE username = ?", (new_h, new_s, u.strip()))
                    return True
                return False
                
            h, _ = self._hash(p, stored_salt)
            return h == stored_hash
        except Exception as e:
            logger.error(f"Erro na verificação admin: {e}")
            return False

    def create_admin(self, u, p):
        try:
            h, s = self._hash(p)
            with self.conn:
                self.conn.execute("INSERT INTO admins(username, password_hash, salt) VALUES (?, ?, ?)", (u.strip(), h, s))
            return True
        except sqlite3.Error as e:
            logger.error(f"Erro ao criar admin: {e}")
            return False

    def ensure_default_admin(self, u, p):
        try:
            if not self.conn.execute("SELECT id FROM admins LIMIT 1").fetchone():
                self.create_admin(u, p)
        except sqlite3.Error: pass


class FaceEngine:
    def __init__(self, cascade_path: Path, model_path: Path, storage: Storage):
        self.cascade = cv2.CascadeClassifier(str(cascade_path))
        self.recognizer = cv2.face.LBPHFaceRecognizer_create(radius=2, neighbors=12, grid_x=8, grid_y=8)
        self.model_path = model_path
        self.storage = storage
        self.model_ready = False
        self.try_load_model()

    def try_load_model(self):
        if self.model_path.exists():
            try:
                self.recognizer.read(str(self.model_path))
                self.model_ready = True
            except: self.model_ready = False

    def detect_face(self, frame):
        # Lógica de detecção idêntica à original
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = self.cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=MIN_FACE_SIZE)
        if len(faces) == 0: return None, None
        # Pega a maior face
        rect = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
        x, y, w, h = rect
        face_roi = gray[y:y+h, x:x+w]
        face_roi = cv2.resize(face_roi, FACE_SIZE, interpolation=cv2.INTER_AREA)
        face_roi = cv2.equalizeHist(face_roi)
        return rect, face_roi

    def train_from_db(self):
        samples = self.storage.get_all_samples()
        if not samples: return False
        images, labels = [], []
        for uid, path in samples:
            img = secure_io.load_decrypted_image(path, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                images.append(cv2.resize(img, FACE_SIZE))
                labels.append(uid)
        if not images: return False
        self.recognizer.train(images, np.array(labels))
        self.recognizer.save(str(self.model_path))
        self.model_ready = True
        return True

    def predict(self, face_gray):
        if not self.model_ready: return -1, 999.0
        return self.recognizer.predict(face_gray)

class AuthController:
    def __init__(self, engine, storage):
        self.engine = engine
        self.storage = storage
        self.denied_until = 0.0
        self.granted_until = 0.0
        self.granted_name = ""
        self.consecutive = 0
        self.last_id = None
        self.last_update_at = {} 
        
        # Liveness check (Vivacidade)
        self.face_history = [] # Armazena ROIs das últimas faces para checar movimento/mudança

    def _check_liveness(self, current_roi):
        """Checa se a face não é uma foto estática verificando variação de pixels."""
        if current_roi is None: return False
        
        # Reduzir ruído
        current_roi = cv2.GaussianBlur(current_roi, (5, 5), 0)
        
        is_alive = True
        if len(self.face_history) > 0:
            last_roi = self.face_history[-1]
            try:
                # Calcula diferença absoluta entre os frames
                diff = cv2.absdiff(last_roi, current_roi)
                score = np.sum(diff) / (current_roi.size)
                
                # Tolerância mais generosa para evitar falsos negativos ou travamentos.
                is_alive = 0.1 < score < 80.0 
            except Exception:
                is_alive = True
            
        self.face_history.append(current_roi)
        if len(self.face_history) > 10: self.face_history.pop(0)
        return is_alive

    def process(self, frame):
        now = time.time()
        rect, face_gray = self.engine.detect_face(frame)
        
        label, detail, color = "SISTEMA ATIVO", "Aguardando detecção facial...", COLOR_INFO

        if now < self.granted_until:
            label, detail, color = "ACESSO LIBERADO", f"Bem-vindo, {self.granted_name}", COLOR_SUCCESS
            VisualHelper.draw_glow(frame, COLOR_SUCCESS)
        elif now < self.denied_until:
            label, detail, color = "ACESSO NEGADO", "Usuário não reconhecido ou inativo", COLOR_DANGER
            VisualHelper.draw_glow(frame, COLOR_DANGER)
        elif rect is not None:
            # Check de Vivacidade
            if not self._check_liveness(face_gray):
                label, detail, color = "VIVACIDADE FALHOU", "Mantenha-se estável e olhe para a câmera", COLOR_INFO
                VisualHelper.draw_hud(frame, rect, label, detail, color)
                return frame

            uid, conf = self.engine.predict(face_gray)
            
            if conf <= CONFIDENCE_THRESHOLD:
                if self.last_id == uid: self.consecutive += 1
                else: self.last_id, self.consecutive = uid, 1
                
                if self.consecutive >= REQUIRED_CONSISTENT_MATCHES:
                    user = self.storage.user_by_id(uid)
                    if user and user.active:
                        self.granted_until, self.granted_name = now + ACCESS_GRANTED_SECONDS, user.name
                        self.storage.log_event("verify_granted", user_id=user.id, confidence=conf)
                        
                        # --- AUTO-UPDATE: SALVAR FOTO DO ACESSO ---
                        last_upd = self.last_update_at.get(user.id, 0.0)
                        if now - last_upd > 20.0: 
                            p = Path(f"data/faces/{user.id}")
                            p.mkdir(parents=True, exist_ok=True)
                            fname = p / f"auto_{time.time_ns()}.enc"
                            secure_io.save_encrypted_image(face_gray, str(fname), quality=85)
                            self.storage.add_sample(user.id, str(fname))
                            self.last_update_at[user.id] = now
                    else:
                        self.denied_until = now + ACCESS_DENIED_SECONDS
                        self.storage.log_event("verify_denied", user_id=uid)

                        denied_dir = Path("data/denied")
                        denied_dir.mkdir(parents=True, exist_ok=True)
                        fname = denied_dir / f"denied_{time.strftime('%Y%m%d_%H%M%S')}.enc"
                        secure_io.save_encrypted_image(frame, str(fname), quality=80)
                    self.consecutive = 0
                else:
                    label, detail = "VALIDANDO...", f"Analisando biometria [{self.consecutive}/{REQUIRED_CONSISTENT_MATCHES}]"
            else:
                self.consecutive = 0
                if now > self.denied_until + 5.0: 
                    self.denied_until = now + ACCESS_DENIED_SECONDS
                    self.storage.log_event("verify_unknown", details="low_confidence")
                    denied_dir = Path("data/denied")
                    denied_dir.mkdir(parents=True, exist_ok=True)
                    fname = denied_dir / f"unknown_{time.strftime('%Y%m%d_%H%M%S')}.enc"
                    secure_io.save_encrypted_image(frame, str(fname), quality=80)        
        VisualHelper.draw_hud(frame, rect, label, detail, color)
        return frame


class VisualHelper:
    @staticmethod
    def draw_glow(frame, color):
        h, w = frame.shape[:2]
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (w, h), color, 30)
        cv2.addWeighted(overlay, 0.4, frame, 0.6, 0, frame)

    @staticmethod
    def draw_hud(frame, rect, label, detail, color):
        if rect is not None:
            x, y, w, h = rect
            l, t = 30, 3
            cv2.line(frame, (x, y), (x+l, y), color, t)
            cv2.line(frame, (x, y), (x, y+l), color, t)
            cv2.line(frame, (x+w, y), (x+w-l, y), color, t)
            cv2.line(frame, (x+w, y), (x+w, y+l), color, t)
            cv2.line(frame, (x, y+h), (x+l, y+h), color, t)
            cv2.line(frame, (x, y+h), (x, y+h-l), color, t)
            cv2.line(frame, (x+w, y+h), (x+w-l, y+h), color, t)
            cv2.line(frame, (x+w, y+h), (x+w, y+h-l), color, t)

        hf, wf = frame.shape[:2]
        # Overlay de Status (Original Style mas HUD Moderno)
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, hf-100), (wf, hf), (15, 23, 42), -1)
        cv2.addWeighted(overlay, 0.7, frame, 0.3, 0, frame)
        cv2.rectangle(frame, (0, hf-100), (10, hf), color, -1)
        cv2.putText(frame, label, (30, hf-60), cv2.FONT_HERSHEY_DUPLEX, 1.0, (255,255,255), 2)
        cv2.putText(frame, detail, (30, hf-25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180,180,180), 1)

def _open_camera(index=0):
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(index, cv2.CAP_MSMF)
    if not cap.isOpened():
        cap.release()
        cap = cv2.VideoCapture(index)
    
    if cap.isOpened():
        # Apenas tenta definir a resolução. O _cam_loop cuidará do aquecimento (warm-up)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
    
    return cap
