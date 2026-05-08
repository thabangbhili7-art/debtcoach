import os
import secrets

from fastapi import APIRouter, Depends, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session
from html import escape

from ..db import get_db
from ..models import User, Debt
from .whatsapp import send_whatsapp, reminder_message, payment_message, normalize_phone

router = APIRouter()
security = HTTPBasic()


def require_login(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.getenv("DASHBOARD_USER", "admin")
    expected_pass = os.getenv("DASHBOARD_PASSWORD", "changeme")

    ok_user = secrets.compare_digest(credentials.username, expected_user)
    ok_pass = secrets.compare_digest(credentials.password, expected_pass)

    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def get_dashboard_user(db: Session):
    user = db.query(User).order_by(User.id.asc()).first()

    if not user:
        user = User(phone_e164="+27000000000")
        db.add(user)
        db.commit()
        db.refresh(user)

    return user


def money(cents: int):
    return f"R{cents // 100}"


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    q: str = "",
    error: str = "",
    success: str = "",
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debts = db.query(Debt).all()

    if q:
        debts = [
            d for d in debts
            if q.lower() in (d.creditor_name or "").lower()
            or q.lower() in (d.phone_number or "").lower()
        ]

    grouped = {}

    for d in debts:
        key = ((d.creditor_name or "").strip().lower(), d.phone_number or "")

        if key not in grouped:
            grouped[key] = {
                "ids": [d.id],
                "name": d.creditor_name,
                "phone": d.phone_number,
                "balance_cents": d.balance_cents,
            }
        else:
            grouped[key]["ids"].append(d.id)
            grouped[key]["balance_cents"] += d.balance_cents

    customers = list(grouped.values())

    total_cents = sum(c["balance_cents"] for c in customers)
    total_customers = len(customers)
    reachable = len([c for c in customers if c["phone"]])

    message = ""

    if error == "invalid_phone":
        message = "<div class='alert error'>Invalid phone number. Use +27712345678 or 0712345678.</div>"
    elif error == "invalid_amount":
        message = "<div class='alert error'>Amount must be greater than 0.</div>"
    elif success == "added":
        message = "<div class='alert success'>Customer added.</div>"
    elif success == "deleted":
        message = "<div class='alert success'>Customer deleted.</div>"
    elif success == "paid":
        message = "<div class='alert success'>Customer marked as paid.</div>"
    elif success == "sent":
        message = "<div class='alert success'>Message sent.</div>"
    elif error == "send_failed":
        message = "<div class='alert error'>Message failed to send. Check phone number or Twilio logs.</div>"

    rows = ""

    for c in customers:
        amount = c["balance_cents"] // 100
        phone = c["phone"] or "No phone"
        debt_id = c["ids"][0]

        rows += f"""
        <tr>
            <td>{c["name"]}</td>
            <td>{phone}</td>
            <td>R{amount}</td>
            <td class="actions">
                <form method="post" action="/dashboard/remind/{debt_id}">
                    <button class="btn blue">Remind</button>
                </form>

                <form method="post" action="/dashboard/pay/{debt_id}">
                    <button class="btn green">Pay Link</button>
                </form>

                <form method="post" action="/dashboard/paid/{debt_id}">
                    <button class="btn gray">Paid</button>
                </form>

                <form method="post" action="/dashboard/delete/{debt_id}" onsubmit="return confirm('Are you sure you want to delete this customer?');">
                    <button class="btn red">Delete</button>
                </form>
            </td>
        </tr>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>DebtCoach Dashboard</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                margin: 0;
                padding: 40px;
            }}

            h1 {{
                font-size: 36px;
                margin-bottom: 8px;
            }}

            .subtitle {{
                color: #94a3b8;
                margin-bottom: 30px;
            }}

            .cards {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
                margin-bottom: 30px;
            }}

            .card {{
                background: #1e293b;
                padding: 24px;
                border-radius: 16px;
                border: 1px solid #334155;
            }}

            .card h2 {{
                font-size: 32px;
                margin: 0;
            }}

            .card p {{
                color: #94a3b8;
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
            }}

            th, td {{
                padding: 16px;
                border-bottom: 1px solid #334155;
                text-align: left;
            }}

            th {{
                background: #111827;
                color: #cbd5e1;
            }}

            .btn {{
                border: none;
                padding: 9px 12px;
                color: white;
                border-radius: 8px;
                cursor: pointer;
                font-weight: bold;
            }}

            .blue {{ background: #2563eb; }}
            .green {{ background: #16a34a; }}
            .gray {{ background: #64748b; }}
            .red {{ background: #dc2626; }}

            .actions {{
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }}

            form {{
                display: inline;
            }}

            .alert {{
                padding: 14px 16px;
                border-radius: 10px;
                margin-bottom: 20px;
                font-weight: bold;
            }}

            .error {{
                background: #7f1d1d;
                color: #fecaca;
            }}

            .success {{
                background: #14532d;
                color: #bbf7d0;
            }}
        </style>
    </head>

    <body>
        <h1>DebtCoach Dashboard</h1>
        <div class="subtitle">Business collections overview</div>

        {message}

        <div class="cards">
            <div class="card"><h2>{money(total_cents)}</h2><p>Total owed</p></div>
            <div class="card"><h2>{total_customers}</h2><p>Customers</p></div>
            <div class="card"><h2>{reachable}</h2><p>Reachable by WhatsApp</p></div>
        </div>

        <div class="panel">
            <h2>Add Customer</h2>
            <form method="post" action="/dashboard/add">
                <input name="name" placeholder="Customer name" required>
                <input name="phone" placeholder="+27712345678">
                <input name="amount" placeholder="Amount" type="number" min="1" required>
                <button class="btn green">Add</button>
            </form>
        </div>

        <div class="panel">
            <form method="get" action="/dashboard">
                <input name="q" placeholder="Search name or phone" value="{escape(q)}">
                <button class="btn blue">Search</button>
                <a href="/dashboard" style="color:#93c5fd;margin-left:10px;">Clear</a>
            </form>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Customer</th>
                    <th>Phone</th>
                    <th>Amount</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
    </body>
    </html>
    """

    return html


@router.post("/dashboard/add")
def add_customer(
    name: str = Form(...),
    phone: str = Form(""),
    amount: int = Form(...),
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    if amount <= 0:
        return RedirectResponse("/dashboard?error=invalid_amount", status_code=303)

    clean_phone = normalize_phone(phone) if phone else None

    if phone and not clean_phone:
        return RedirectResponse("/dashboard?error=invalid_phone", status_code=303)

    user = get_dashboard_user(db)

    debt = Debt(
        user_id=user.id,
        creditor_name=name.strip(),
        phone_number=clean_phone,
        balance_cents=amount * 100,
    )

    db.add(debt)
    db.commit()

    return RedirectResponse("/dashboard?success=added", status_code=303)


@router.post("/dashboard/remind/{debt_id}")
def dashboard_remind(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        ok, error = send_whatsapp(
            debt.phone_number,
            reminder_message(debt.creditor_name, amount),
        )

        if ok:
            return RedirectResponse("/dashboard?success=sent", status_code=303)

    return RedirectResponse("/dashboard?error=send_failed", status_code=303)


@router.post("/dashboard/pay/{debt_id}")
def dashboard_pay(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        ok, error = send_whatsapp(
            debt.phone_number,
            payment_message(debt.creditor_name, amount),
        )

        if ok:
            return RedirectResponse("/dashboard?success=sent", status_code=303)

    return RedirectResponse("/dashboard?error=send_failed", status_code=303)


@router.post("/dashboard/paid/{debt_id}")
def dashboard_paid(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt:
        debt.balance_cents = 0
        db.add(debt)
        db.commit()

    return RedirectResponse("/dashboard?success=paid", status_code=303)


@router.post("/dashboard/delete/{debt_id}")
def dashboard_delete(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt:
        db.delete(debt)
        db.commit()

    return RedirectResponse("/dashboard?success=deleted", status_code=303)