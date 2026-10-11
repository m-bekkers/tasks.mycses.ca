import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from typing import Literal

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field, field_validator
from starlette.middleware.sessions import SessionMiddleware
from openproject import OpenProjectClient, OpenProjectError

logger = logging.getLogger(__name__)

BASE_URL = os.environ.get(
    "BASE_URL", "https://tasks.mycses.ca"
).rstrip("/")
DATABASE_PATH = os.environ.get("DATABASE_PATH", "/data/portal.db")
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

ALLOWED_EMAIL_DOMAINS = {
    value.strip().lower().lstrip("@")
    for value in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",")
    if value.strip()
}
ADMIN_EMAILS = {
    value.strip().lower()
    for value in os.environ.get("ADMIN_EMAILS", "").split(",")
    if value.strip()
}

if not SESSION_SECRET:
    raise RuntimeError("SESSION_SECRET must be configured")
if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
    raise RuntimeError("Google OAuth credentials must be configured")
if not ALLOWED_EMAIL_DOMAINS:
    raise RuntimeError("ALLOWED_EMAIL_DOMAINS must be configured")
if not BASE_URL.startswith("https://"):
    raise RuntimeError("BASE_URL must use HTTPS")


@contextmanager
def database():
    db = sqlite3.connect(DATABASE_PATH)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize_database():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    with database() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                google_sub TEXT UNIQUE,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                name TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL DEFAULT 'affiliate'
                    CHECK (role IN ('affiliate', 'staff', 'admin')),
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT
            )
        """)


app = FastAPI(title="CSES Affiliates Portal API")

app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="tasks_portal_session",
    same_site="lax",
    https_only=True,
    max_age=8 * 60 * 60,
)

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url=(
        "https://accounts.google.com/.well-known/openid-configuration"
    ),
    client_kwargs={"scope": "openid email profile"},
)


class NewUser(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["affiliate", "staff", "admin"] = "affiliate"
    name: str = Field(default="", max_length=200)


class UserUpdate(BaseModel):
    role: Literal["affiliate", "staff", "admin"] | None = None
    active: bool | None = None


class RequestSubmission(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=254)
    affiliate: str = Field(min_length=1, max_length=200)
    request_type: Literal["account", "partnership", "content", "technical", "other"]
    details: str = Field(min_length=1, max_length=20000)

    @field_validator("name", "affiliate", "details")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank")
        return value


class WorkPackageUpdate(BaseModel):
    lock_version: int = Field(ge=0)
    subject: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    status_id: int | None = Field(default=None, ge=1)
    priority_id: int | None = Field(default=None, ge=1)
    assignee_id: int | None = Field(default=None, ge=1)


REQUEST_TYPE_LABELS = {
    "account": "Account help",
    "partnership": "Partnership",
    "content": "Content or campaign",
    "technical": "Technical support",
    "other": "Something else",
}


def normalize_email(value: str) -> str:
    email = value.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=400, detail="Invalid email address")
    return email


def require_user(request: Request):
    google_sub = request.session.get("google_sub")
    if not google_sub:
        raise HTTPException(status_code=401, detail="Not signed in")

    with database() as db:
        user = db.execute(
            "SELECT * FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()

    if not user or not user["active"]:
        request.session.clear()
        raise HTTPException(status_code=401, detail="Account unavailable")

    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def openproject_call(operation):
    try:
        return operation()
    except OpenProjectError as error:
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error


@app.on_event("startup")
def startup():
    initialize_database()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/auth/google/login")
async def google_login(request: Request):
    return await oauth.google.authorize_redirect(
        request, f"{BASE_URL}/auth/google/callback"
    )


@app.get("/auth/google/callback")
async def google_callback(request: Request):
    try:
        token = await oauth.google.authorize_access_token(request)
        identity = token.get("userinfo") or {}

        google_sub = identity.get("sub")
        email = normalize_email(identity.get("email", ""))
        name = (identity.get("name") or "").strip()
        verified = identity.get("email_verified") is True

        if not google_sub or not verified:
            raise HTTPException(
                status_code=403,
                detail="A verified Google email is required",
            )

        is_configured_admin = email in ADMIN_EMAILS
        domain = email.rsplit("@", 1)[1]

        with database() as db:
            # First find an account already linked to this Google identity.
            user = db.execute(
                "SELECT * FROM users WHERE google_sub = ?",
                (google_sub,),
            ).fetchone()

            if user:
                if not user["active"]:
                    raise HTTPException(
                        status_code=403, detail="Your account is disabled"
                    )
                role = "admin" if is_configured_admin else user["role"]
                db.execute(
                    """UPDATE users
                       SET email = ?, name = ?, role = ?,
                           last_login = CURRENT_TIMESTAMP
                       WHERE id = ?""",
                    (email, name, role, user["id"]),
                )
            else:
                # An administrator may have created this account in advance.
                # A verified Google identity can claim the matching email.
                user = db.execute(
                    "SELECT * FROM users WHERE email = ?",
                    (email,),
                ).fetchone()

                if user:
                    if not user["active"]:
                        raise HTTPException(
                            status_code=403, detail="Your account is disabled"
                        )
                    if user["google_sub"] not in (None, google_sub):
                        raise HTTPException(
                            status_code=409,
                            detail="This email is linked to another Google identity",
                        )

                    role = "admin" if is_configured_admin else user["role"]
                    db.execute(
                        """UPDATE users
                           SET google_sub = ?, name = ?, role = ?,
                               last_login = CURRENT_TIMESTAMP
                           WHERE id = ?""",
                        (google_sub, name, role, user["id"]),
                    )
                else:
                    # Only new, self-registering users need an allowed domain.
                    if domain not in ALLOWED_EMAIL_DOMAINS and not is_configured_admin:
                        raise HTTPException(
                            status_code=403,
                            detail="Your email domain is not eligible",
                        )

                    role = "admin" if is_configured_admin else "affiliate"
                    db.execute(
                        """INSERT INTO users
                           (google_sub, email, name, role, last_login)
                           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)""",
                        (google_sub, email, name, role),
                    )

        request.session.clear()
        request.session["google_sub"] = google_sub
        return RedirectResponse(url="/requests/", status_code=303)

    except HTTPException:
        raise
    except Exception:
        return JSONResponse(status_code=401, content={"detail": "Google sign-in failed"},)

@app.get("/api/me")
def current_user(request: Request):
    user = require_user(request)
    return {
        "id": user["id"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
    }


@app.post("/api/requests", status_code=201)
def submit_request(body: RequestSubmission, request: Request):
    user = require_user(request)
    contact_email = normalize_email(body.email)
    subject = f"{body.affiliate.strip()} - {REQUEST_TYPE_LABELS[body.request_type]}"
    description = (
        f"Submitted through the CSES Affiliates Portal by: {user['name']} ({user['email']})\n\n"
        f"Contact name: {body.name.strip()}\n"
        f"Contact email: {contact_email}\n"
        f"Affiliate: {body.affiliate.strip()}\n"
        f"Request type: {REQUEST_TYPE_LABELS[body.request_type]}\n\n"
        f"{body.details.strip()}"
    )
    created = openproject_call(
        lambda: OpenProjectClient().create_request(
            subject=subject,
            description=description,
        )
    )
    return {
        "id": created["id"],
        "subject": created["subject"],
        "url": created["url"],
    }


@app.post("/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"status": "signed_out"}


@app.get("/api/admin/users")
def list_users(request: Request):
    require_admin(request)
    with database() as db:
        users = db.execute("""
            SELECT id, email, name, role, active, created_at, last_login
            FROM users ORDER BY email
        """).fetchall()
    return [dict(user) for user in users]


@app.get("/api/admin/work-packages")
def list_open_work_packages(request: Request):
    require_admin(request)
    return openproject_call(lambda: OpenProjectClient().list_open_work_packages())


@app.patch("/api/admin/work-packages/{work_package_id}")
def update_work_package(
    work_package_id: int,
    body: WorkPackageUpdate,
    request: Request,
):
    require_admin(request)
    changes = body.model_dump(exclude_unset=True)
    if not any(key != "lock_version" for key in changes):
        raise HTTPException(status_code=400, detail="No work-package changes supplied")
    if "subject" in changes and changes["subject"] is None:
        raise HTTPException(status_code=400, detail="Subject cannot be null")
    return openproject_call(
        lambda: OpenProjectClient().update_work_package(work_package_id, changes)
    )


@app.post("/api/admin/users", status_code=201)
def add_user(body: NewUser, request: Request):
    require_admin(request)
    email = normalize_email(body.email)

    with database() as db:
        try:
            cursor = db.execute(
                """INSERT INTO users (email, name, role, active)
                   VALUES (?, ?, ?, 1)""",
                (email, body.name.strip(), body.role),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(
                status_code=409, detail="An account with this email already exists"
            )

        user = db.execute(
            """SELECT id, email, name, role, active, created_at, last_login
               FROM users WHERE id = ?""",
            (cursor.lastrowid,),
        ).fetchone()
    return dict(user)


@app.patch("/api/admin/users/{user_id}")
def update_user(user_id: int, body: UserUpdate, request: Request):
    admin = require_admin(request)
    changes = body.model_dump(exclude_unset=True)

    if not changes:
        raise HTTPException(status_code=400, detail="No changes supplied")
    if "role" in changes and changes["role"] is None:
        raise HTTPException(status_code=400, detail="Role cannot be null")
    if "active" in changes and changes["active"] is None:
        raise HTTPException(status_code=400, detail="Active status cannot be null")
    if user_id == admin["id"] and (
        changes.get("role") not in (None, "admin")
        or changes.get("active") is False
    ):
        raise HTTPException(
            status_code=400,
            detail="You cannot remove your own administrator access",
        )

    with database() as db:
        target = db.execute(
            "SELECT id, role, active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if not target:
            raise HTTPException(status_code=404, detail="User not found")

        if target["role"] == "admin" and (
            changes.get("role") not in (None, "admin")
            or changes.get("active") is False
        ):
            other_admin = db.execute(
                """SELECT COUNT(*) AS count FROM users
                   WHERE role = 'admin' AND active = 1 AND id != ?""",
                (user_id,),
            ).fetchone()["count"]
            if other_admin == 0:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot disable or demote the last active administrator",
                )

        assignments = ", ".join(f"{key} = ?" for key in changes)
        values = [
            int(value) if key == "active" else value
            for key, value in changes.items()
        ]
        db.execute(
            f"UPDATE users SET {assignments} WHERE id = ?",
            (*values, user_id),
        )
        updated = db.execute(
            """SELECT id, email, name, role, active, created_at, last_login
               FROM users WHERE id = ?""",
            (user_id,),
        ).fetchone()

    return dict(updated)
