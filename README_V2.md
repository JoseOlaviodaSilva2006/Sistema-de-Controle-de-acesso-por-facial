# Facial Auth V2

This is an upgraded implementation of the facial authentication pipeline with:

- Modernized stack: Python + OpenCV (contrib/LBPH) + SQLite
- Reliable enrollment pipeline with sample persistence + model retraining
- Non-blocking verification loop
- Automatic denial cooldown behavior:
  - On mismatch: show `Access Denied`
  - Keep camera feed running
  - Automatically resume scanning after 3 seconds

## Why V2 exists

The original project in this workspace is shipped as a compiled `.jar` without source code, which prevents deep logic changes in-place.  
`facial_auth_v2.py` provides an editable and extensible production-oriented foundation.

## Setup

1. Create virtual environment (recommended):
   - `python -m venv .venv`
   - `.venv\Scripts\activate`
2. Install dependencies:
   - `pip install -r requirements.txt`

## Usage

### 0) Open visual launcher (with ADM login button)

`python launcher_ui.py`

- Buttons available:
  - `Login ADM`
  - `Cadastrar usuário (enrollment)` (requires ADM login)
  - `Verificar acesso (live)`
  - `Retreinar modelo` (requires ADM login)
  - `Gerenciar usuários (CRUD)` (requires ADM login)
  - `Criar novo ADM` (requires ADM login)
- Default ADM password: `admin123`
- Default ADM user: `admin`

### User CRUD (ADM)

In `Gerenciar usuários (CRUD)`, ADM can:

- Create users
- Edit users
- Inactivate / reactivate users
- View all saved user images (double-click to open)
- Start enrollment for selected user

Inactive users are always denied access.  
Even when inactive, recognized verification frames are still saved to keep profile images updated.

### 1) Enroll user

`python facial_auth_v2.py enroll --name "Alice"`

- Captures 25 face samples by default.
- Saves samples under `data/faces/<user_id>/`.
- Retrains LBPH model after successful enrollment.

### 2) Verify user (live)

`python facial_auth_v2.py verify`

Verification behavior:
- Continuous camera scanning (non-blocking).
- On failed verification, displays `Access Denied` for 3 seconds.
- Automatically resumes face scanning after cooldown.

### 3) Retrain model manually

`python facial_auth_v2.py retrain`

## Tunables

In `facial_auth_v2.py`, you can adjust:

- `REQUIRED_SAMPLES`
- `CONFIDENCE_THRESHOLD`
- `REQUIRED_CONSISTENT_MATCHES`
- `ACCESS_DENIED_SECONDS`
- `FACE_SIZE`
- `MIN_FACE_SIZE`

## Reliability notes

- Each auth action is logged in `access_control_v2.db` (`auth_events` table).
- If model file is missing/corrupted, verification attempts retraining from stored samples.
- Enrollment does not block UI with long waits; processing runs frame-by-frame.
- On each successful verification, the validated face frame is automatically saved as a new user sample (with interval control), keeping profiles up to date over time.
