import secrets
from datetime import datetime, timedelta, timezone
from html import escape

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, Debt, Invite
from .auth import get_current_user

router = APIRouter()


def require_admin(request: Request, db: Session):
    current_user = get_current_user(request, db)

    if not current_user:
        return None

    if not current_user.is_admin:
        return None

    return current_user


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(
    request: Request,
    success: str = "",
    error: str = "",
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    if not admin:
        return RedirectResponse("/login", status_code=303)

    users = db.query(User).order_by(User.id.desc()).all()
    invites = db.query(Invite).order_by(Invite.id.desc()).limit(20).all()

    message = ""

    if success == "invite_created":
        message = "<div class='alert success'>Invite created.</div>"
    elif success == "deactivated":
        message = "<div class='alert success'>Business deactivated.</div>"
    elif success == "activated":
        message = "<div class='alert success'>Business activated.</div>"
    elif success == "deleted":
        message = "<div class='alert success'>Business deleted.</div>"
    elif error:
        message = "<div class='alert error'>Something went wrong.</div>"

    user_rows = ""

    for u in users:
        debt_count = db.query(Debt).filter(Debt.user_id == u.id).count()
        status = "Active" if u.is_active else "Inactive"
        role = "Admin" if u.is_admin else "Business"

        action = ""

        if not u.is_admin:
            if u.is_active:
                action += f"""
                <form method="post" action="/admin/users/{u.id}/deactivate">
                    <button class="btn gray">Deactivate</button>
                </form>
                """
            else:
                action += f"""
                <form method="post" action="/admin/users/{u.id}/activate">
                    <button class="btn green">Activate</button>
                </form>
                """

            action += f"""
            <form method="post" action="/admin/users/{u.id}/delete" onsubmit="return confirm('Delete this business and all its debtors?');">
                <button class="btn red">Delete</button>
            </form>
            """

        user_rows += f"""
        <tr>
            <td>{escape(u.business_name or "No name")}</td>
            <td>{escape(u.email or "No email")}</td>
            <td>{escape(u.phone_e164 or "No WhatsApp")}</td>
            <td>{role}</td>
            <td>{status}</td>
            <td>{debt_count}</td>
            <td class="actions">{action}</td>
        </tr>
        """

    invite_rows = ""

    for inv in invites:
        used = "Yes" if inv.used else "No"
        link = f"/register?invite={inv.code}"

        invite_rows += f"""
        <tr>
            <td>{escape(inv.business_name or "")}</td>
            <td>{escape(inv.email or "")}</td>
            <td>{used}</td>
            <td>{escape(str(inv.expires_at or ""))}</td>
            <td><code>{escape(link)}</code></td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>DebtCoach Admin</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                padding: 40px;
            }}

            .top {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 24px;
            }}

            .panel {{
                background: #1e293b;
                border: 1px solid #334155;
                border-radius: 16px;
                padding: 20px;
                margin-bottom: 24px;
            }}

            input {{
                padding: 12px;
                border-radius: 8px;
                border: 1px solid #334155;
                background: #0f172a;
                color: white;
                margin-right: 8px;
            }}

            table {{
                width: 100%;
                border-collapse: collapse;
                background: #1e293b;
                border-radius: 16px;
                overflow: hidden;
                margin-bottom: 30px;
            }}

            th, td {{
                padding: 14px;
                border-bottom: 1px solid #334155;
                text-align: left;
            }}

            th {{
                background: #111827;
                color: #cbd5e1;
            }}

            .btn {{
                border: none;
                padding: 8px 12px;
                color: white;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }}

            .green {{ background: #16a34a; }}
            .gray {{ background: #64748b; }}
            .red {{ background: #dc2626; }}
            .blue {{ background: #2563eb; }}

            .actions {{
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }}

            .alert {{
                padding: 14px;
                border-radius: 10px;
                margin-bottom: 20px;
                font-weight: bold;
            }}

            .success {{
                background: #14532d;
                color: #bbf7d0;
            }}

            .error {{
                background: #7f1d1d;
                color: #fecaca;
            }}

            a {{
                color: #93c5fd;
            }}

            code {{
                color: #bbf7d0;
            }}
        </style>
    </head>
    <body>
        <div class="top">
            <div>
                <h1>DebtCoach Owner Admin</h1>
                <p>Manage businesses, invites, and access.</p>
            </div>
            <div>
                <a href="/dashboard">Dashboard</a> |
                <a href="/logout">Logout</a>
            </div>
        </div>

        {message}

        <div class="panel">
            <h2>Create One-Time Invite</h2>
            <form method="post" action="/admin/invites/create">
                <input name="business_name" placeholder="Business name">
                <input name="email" type="email" placeholder="Business email">
                <button class="btn blue">Create Invite</button>
            </form>
        </div>

        <h2>Businesses</h2>
        <table>
            <thead>
                <tr>
                    <th>Business</th>
                    <th>Email</th>
                    <th>WhatsApp</th>
                    <th>Role</th>
                    <th>Status</th>
                    <th>Debtors</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>{user_rows}</tbody>
        </table>

        <h2>Recent Invites</h2>
        <table>
            <thead>
                <tr>
                    <th>Business</th>
                    <th>Email</th>
                    <th>Used</th>
                    <th>Expires</th>
                    <th>Register Link</th>
                </tr>
            </thead>
            <tbody>{invite_rows}</tbody>
        </table>
    </body>
    </html>
    """

    return html


@router.post("/admin/invites/create")
def create_invite(
    request: Request,
    business_name: str = Form(""),
    email: str = Form(""),
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    if not admin:
        return RedirectResponse("/login", status_code=303)

    code = secrets.token_urlsafe(32)

    invite = Invite(
        code=code,
        business_name=business_name.strip() or None,
        email=email.lower().strip() or None,
        used=False,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
    )

    db.add(invite)
    db.commit()

    return RedirectResponse("/admin?success=invite_created", status_code=303)


@router.post("/admin/users/{user_id}/deactivate")
def deactivate_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    if not admin:
        return RedirectResponse("/login", status_code=303)

    user = db.query(User).filter(User.id == user_id, User.is_admin == False).first()

    if user:
        user.is_active = False
        db.add(user)
        db.commit()

    return RedirectResponse("/admin?success=deactivated", status_code=303)


@router.post("/admin/users/{user_id}/activate")
def activate_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    if not admin:
        return RedirectResponse("/login", status_code=303)

    user = db.query(User).filter(User.id == user_id, User.is_admin == False).first()

    if user:
        user.is_active = True
        db.add(user)
        db.commit()

    return RedirectResponse("/admin?success=activated", status_code=303)


@router.post("/admin/users/{user_id}/delete")
def delete_user(
    request: Request,
    user_id: int,
    db: Session = Depends(get_db),
):
    admin = require_admin(request, db)

    if not admin:
        return RedirectResponse("/login", status_code=303)

    user = db.query(User).filter(User.id == user_id, User.is_admin == False).first()

    if user:
        db.query(Debt).filter(Debt.user_id == user.id).delete()
        db.delete(user)
        db.commit()

    return RedirectResponse("/admin?success=deleted", status_code=303)