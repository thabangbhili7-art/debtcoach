import os
import secrets

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, Debt
from .whatsapp import send_whatsapp, reminder_message, payment_message

router = APIRouter()
security = HTTPBasic()


def require_login(credentials: HTTPBasicCredentials = Depends(security)):
    expected_user = os.getenv("DASHBOARD_USER", "admin")
    expected_pass = os.getenv("DASHBOARD_PASSWORD", "changeme")

    ok_user = secrets.compare_digest(credentials.username, expected_user)
    ok_pass = secrets.compare_digest(credentials.password, expected_pass)

    if not (ok_user and ok_pass):
        from fastapi import HTTPException
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


def normalize_phone(phone: str):
    phone = (phone or "").strip().replace(" ", "")
    if phone.startswith("0"):
        phone = "+27" + phone[1:]
    return phone


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    q: str = "",
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

    # Remove duplicates visually by grouping same customer name + phone
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

    total_rands = sum(c["balance_cents"] for c in customers) // 100
    total_customers = len(customers)
    reachable = len([c for c in customers if c["phone"]])

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
            h1 {{ font-size: 36px; margin-bottom: 8px; }}
            .subtitle {{ color: #94a3b8; margin-bottom: 30px; }}
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
            .card h2 {{ font-size: 32px; margin: 0; }}
            .card p {{ color: #94a3b8; }}
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
            th {{ background: #111827; color: #cbd5e1; }}
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
            .actions {{
                display: flex;
                gap: 8px;
            }}
            form {{ display: inline; }}
        </style>
    </head>
    <body>
        <h1>DebtCoach Dashboard</h1>
        <div class="subtitle">Business collections overview</div>

        <div class="cards">
            <div class="card"><h2>R{total_rands}</h2><p>Total owed</p></div>
            <div class="card"><h2>{total_customers}</h2><p>Customers</p></div>
            <div class="card"><h2>{reachable}</h2><p>Reachable by WhatsApp</p></div>
        </div>

        <div class="panel">
            <h2>Add Customer</h2>
            <form method="post" action="/dashboard/add">
                <input name="name" placeholder="Customer name" required>
                <input name="phone" placeholder="+27712345678">
                <input name="amount" placeholder="Amount" required>
                <button class="btn green">Add</button>
            </form>
        </div>

        <div class="panel">
            <form method="get" action="/dashboard">
                <input name="q" placeholder="Search name or phone" value="{q}">
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
    user = get_dashboard_user(db)

    debt = Debt(
        user_id=user.id,
        creditor_name=name,
        phone_number=normalize_phone(phone) if phone else None,
        balance_cents=amount * 100,
    )

    db.add(debt)
    db.commit()

    return RedirectResponse("/dashboard", status_code=303)


@router.post("/dashboard/remind/{debt_id}")
def dashboard_remind(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        send_whatsapp(
            debt.phone_number,
            reminder_message(debt.creditor_name, amount),
        )

    return RedirectResponse("/dashboard", status_code=303)


@router.post("/dashboard/pay/{debt_id}")
def dashboard_pay(
    debt_id: int,
    db: Session = Depends(get_db),
    _: None = Depends(require_login),
):
    debt = db.query(Debt).filter(Debt.id == debt_id).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        send_whatsapp(
            debt.phone_number,
            payment_message(debt.creditor_name, amount),
        )

    return RedirectResponse("/dashboard", status_code=303)


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

    return RedirectResponse("/dashboard", status_code=303)