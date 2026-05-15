import csv
import io
from datetime import datetime
from html import escape

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Debt, Payment
from .auth import get_current_user
from .whatsapp import (
    normalize_phone,
    send_payment_reminder,
    send_payment_link,
    send_payment_received,
)

router = APIRouter()


def money(cents: int):
    return f"R{(cents or 0) // 100}"


def format_dt(value):
    if not value:
        return "Not scheduled"
    return str(value).split(".")[0]


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(
    request: Request,
    q: str = "",
    error: str = "",
    success: str = "",
    count: str = "",
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debts = db.query(Debt).filter(Debt.user_id == current_user.id).all()

    if q:
        debts = [
            d for d in debts
            if q.lower() in (d.creditor_name or "").lower()
            or q.lower() in (d.phone_number or "").lower()
        ]

    grouped = {}

    for d in debts:
        key = ((d.creditor_name or "").strip().lower(), d.phone_number or "")

        original = d.original_amount_cents or d.balance_cents or 0

        if key not in grouped:
            grouped[key] = {
                "ids": [d.id],
                "name": d.creditor_name,
                "phone": d.phone_number,
                "balance_cents": d.balance_cents or 0,
                "original_amount_cents": original,
                "next_reminder_at": d.next_reminder_at,
                "due_date": d.due_date,
            }
        else:
            grouped[key]["ids"].append(d.id)
            grouped[key]["balance_cents"] += d.balance_cents or 0
            grouped[key]["original_amount_cents"] += original

            if d.next_reminder_at:
                grouped[key]["next_reminder_at"] = d.next_reminder_at

    customers = list(grouped.values())

    total_original_cents = sum(c["original_amount_cents"] for c in customers)
    total_remaining_cents = sum(c["balance_cents"] for c in customers)
    total_paid_cents = max(0, total_original_cents - total_remaining_cents)

    total_customers = len(customers)
    reachable = len([c for c in customers if c["phone"]])

    message = ""

    if error == "invalid_phone":
        message = "<div class='alert error'>Invalid phone number. Use +27712345678 or 0712345678.</div>"
    elif error == "invalid_amount":
        message = "<div class='alert error'>Amount must be greater than 0.</div>"
    elif error == "send_failed":
        message = "<div class='alert error'>Message failed. Check phone number, template approval, or Twilio logs.</div>"
    elif error == "csv_failed":
        message = "<div class='alert error'>CSV upload failed. Use columns: name, phone, amount.</div>"
    elif error == "invalid_date":
        message = "<div class='alert error'>Invalid reminder date.</div>"
    elif success == "added":
        message = "<div class='alert success'>Customer added.</div>"
    elif success == "deleted":
        message = "<div class='alert success'>Customer deleted.</div>"
    elif success == "paid":
        message = "<div class='alert success'>Customer marked as paid.</div>"
    elif success == "payment_recorded":
        message = "<div class='alert success'>Payment recorded.</div>"
    elif success == "scheduled":
        message = "<div class='alert success'>Reminder scheduled.</div>"
    elif success == "sent":
        message = "<div class='alert success'>Message sent.</div>"
    elif success == "uploaded":
        message = f"<div class='alert success'>CSV uploaded successfully. Imported {escape(count or '0')} customer(s).</div>"

    rows = ""

    for c in customers:
        remaining = c["balance_cents"] // 100
        original = c["original_amount_cents"] // 100
        paid = max(0, original - remaining)
        phone = c["phone"] or "No phone"
        debt_id = c["ids"][0]

        status = "Pending"
        status_class = "pending"

        if c["balance_cents"] <= 0:
            status = "Paid"
            status_class = "paid"
        elif not c["phone"]:
            status = "No phone"
            status_class = "warning"

        rows += f"""
        <tr>
            <td>{escape(c["name"] or "")}</td>
            <td>{escape(phone)}</td>
            <td>R{original}</td>
            <td>R{paid}</td>
            <td>R{remaining}</td>
            <td><span class="badge {status_class}">{status}</span></td>
            <td>{escape(format_dt(c["next_reminder_at"]))}</td>
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

                <form method="post" action="/dashboard/payment/{debt_id}">
                    <input name="amount" type="number" min="1" placeholder="Paid" class="small-input" required>
                    <button class="btn green">Record</button>
                </form>

                <form method="post" action="/dashboard/schedule/{debt_id}">
                    <input name="next_reminder_at" type="datetime-local" class="date-input" required>
                    <button class="btn blue">Schedule</button>
                </form>

                <a class="btn blue link-btn" href="/dashboard/customer/{debt_id}">Timeline</a>

                <form method="post" action="/dashboard/delete/{debt_id}" onsubmit="return confirm('Are you sure you want to delete this customer?');">
                    <button class="btn red">Delete</button>
                </form>
            </td>
        </tr>
        """

    business_name = current_user.business_name or "DebtCoach"

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

            .top {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 20px;
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
                grid-template-columns: repeat(5, 1fr);
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
                font-size: 28px;
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

            .small-input {{
                width: 75px;
                padding: 9px;
            }}

            .date-input {{
                width: 175px;
                padding: 9px;
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
                vertical-align: middle;
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
                text-decoration: none;
                font-size: 14px;
            }}

            .blue {{ background: #2563eb; }}
            .green {{ background: #16a34a; }}
            .gray {{ background: #64748b; }}
            .red {{ background: #dc2626; }}

            .link-btn {{
                display: inline-block;
            }}

            .actions {{
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
                align-items: center;
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

            a {{
                color: #93c5fd;
            }}

            .hint {{
                color: #94a3b8;
                font-size: 14px;
                margin-top: 4px;
            }}

            .badge {{
                padding: 6px 10px;
                border-radius: 999px;
                font-size: 13px;
                font-weight: bold;
            }}

            .paid {{
                background: #14532d;
                color: #bbf7d0;
            }}

            .pending {{
                background: #78350f;
                color: #fde68a;
            }}

            .warning {{
                background: #7f1d1d;
                color: #fecaca;
            }}
        </style>
    </head>

    <body>
        <div class="top">
            <div>
                <h1>DebtCoach Dashboard</h1>
                <div class="subtitle">{escape(business_name)} collections overview</div>
            </div>
            <a href="/logout">Logout</a>
        </div>

        {message}

        <div class="cards">
            <div class="card"><h2>{money(total_original_cents)}</h2><p>Total debt</p></div>
            <div class="card"><h2>{money(total_paid_cents)}</h2><p>Total paid</p></div>
            <div class="card"><h2>{money(total_remaining_cents)}</h2><p>Remaining</p></div>
            <div class="card"><h2>{total_customers}</h2><p>Customers</p></div>
            <div class="card"><h2>{reachable}</h2><p>Reachable</p></div>
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
            <h2>Bulk Upload CSV</h2>
            <div class="hint">CSV columns required: name, phone, amount</div>
            <br>
            <form method="post" action="/dashboard/upload" enctype="multipart/form-data">
                <input name="file" type="file" accept=".csv" required>
                <button class="btn green">Upload CSV</button>
            </form>
        </div>

        <div class="panel">
            <form method="get" action="/dashboard">
                <input name="q" placeholder="Search name or phone" value="{escape(q)}">
                <button class="btn blue">Search</button>
                <a href="/dashboard" style="margin-left:10px;">Clear</a>
            </form>
        </div>

        <table>
            <thead>
                <tr>
                    <th>Customer</th>
                    <th>Phone</th>
                    <th>Total Debt</th>
                    <th>Paid</th>
                    <th>Remaining</th>
                    <th>Status</th>
                    <th>Next Reminder</th>
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
    request: Request,
    name: str = Form(...),
    phone: str = Form(""),
    amount: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    if amount <= 0:
        return RedirectResponse("/dashboard?error=invalid_amount", status_code=303)

    clean_phone = normalize_phone(phone) if phone else None

    if phone and not clean_phone:
        return RedirectResponse("/dashboard?error=invalid_phone", status_code=303)

    amount_cents = amount * 100

    debt = Debt(
        user_id=current_user.id,
        creditor_name=name.strip(),
        phone_number=clean_phone,
        balance_cents=amount_cents,
        original_amount_cents=amount_cents,
    )

    db.add(debt)
    db.commit()

    return RedirectResponse("/dashboard?success=added", status_code=303)


@router.post("/dashboard/upload")
async def upload_csv(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    try:
        contents = await file.read()
        decoded = contents.decode("utf-8-sig")

        reader = csv.DictReader(io.StringIO(decoded))
        required_columns = {"name", "phone", "amount"}

        if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
            return RedirectResponse("/dashboard?error=csv_failed", status_code=303)

        imported = 0

        for row in reader:
            name = (row.get("name") or "").strip()
            phone = (row.get("phone") or "").strip()
            amount_raw = (row.get("amount") or "").strip()

            if not name or not amount_raw:
                continue

            try:
                amount = int(float(amount_raw))
            except Exception:
                continue

            if amount <= 0:
                continue

            clean_phone = normalize_phone(phone) if phone else None

            if phone and not clean_phone:
                continue

            amount_cents = amount * 100

            debt = Debt(
                user_id=current_user.id,
                creditor_name=name,
                phone_number=clean_phone,
                balance_cents=amount_cents,
                original_amount_cents=amount_cents,
            )

            db.add(debt)
            imported += 1

        db.commit()

        return RedirectResponse(
            f"/dashboard?success=uploaded&count={imported}",
            status_code=303,
        )

    except Exception as e:
        print("CSV UPLOAD ERROR:", str(e))
        return RedirectResponse("/dashboard?error=csv_failed", status_code=303)


@router.post("/dashboard/payment/{debt_id}")
def record_payment(
    request: Request,
    debt_id: int,
    amount: int = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if not debt or amount <= 0:
        return RedirectResponse("/dashboard?error=invalid_amount", status_code=303)

    payment_cents = amount * 100

    payment = Payment(
        user_id=current_user.id,
        debt_id=debt.id,
        amount_cents=payment_cents,
        note="Partial payment recorded",
    )

    debt.balance_cents = max(0, debt.balance_cents - payment_cents)

    db.add(payment)
    db.add(debt)
    db.commit()

    return RedirectResponse("/dashboard?success=payment_recorded", status_code=303)


@router.post("/dashboard/schedule/{debt_id}")
def schedule_reminder(
    request: Request,
    debt_id: int,
    next_reminder_at: str = Form(...),
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if not debt:
        return RedirectResponse("/dashboard", status_code=303)

    try:
        debt.next_reminder_at = datetime.fromisoformat(next_reminder_at)
        db.add(debt)
        db.commit()
        return RedirectResponse("/dashboard?success=scheduled", status_code=303)
    except Exception:
        return RedirectResponse("/dashboard?error=invalid_date", status_code=303)


@router.get("/dashboard/customer/{debt_id}", response_class=HTMLResponse)
def customer_timeline(
    request: Request,
    debt_id: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if not debt:
        return RedirectResponse("/dashboard", status_code=303)

    payments = db.query(Payment).filter(
        Payment.debt_id == debt.id,
        Payment.user_id == current_user.id,
    ).order_by(Payment.created_at.desc()).all()

    total_debt = debt.original_amount_cents or debt.balance_cents or 0
    total_paid = sum(p.amount_cents for p in payments)
    remaining = debt.balance_cents or 0

    payment_rows = ""

    for p in payments:
        payment_rows += f"""
        <tr>
            <td>Payment</td>
            <td>R{p.amount_cents // 100}</td>
            <td>{escape(p.note or "")}</td>
            <td>{p.created_at}</td>
        </tr>
        """

    html = f"""
    <html>
    <head>
        <title>Customer Timeline</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                background: #0f172a;
                color: white;
                padding: 40px;
            }}

            .card {{
                background: #1e293b;
                padding: 24px;
                border-radius: 16px;
                border: 1px solid #334155;
                margin-bottom: 24px;
            }}

            .cards {{
                display: grid;
                grid-template-columns: repeat(3, 1fr);
                gap: 20px;
                margin-bottom: 24px;
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
            }}

            a {{
                color: #93c5fd;
            }}
        </style>
    </head>
    <body>
        <a href="/dashboard">← Back to dashboard</a>

        <div class="card">
            <h1>{escape(debt.creditor_name)}</h1>
            <p>Phone: {escape(debt.phone_number or "No phone")}</p>
            <p>Next reminder: {escape(format_dt(debt.next_reminder_at))}</p>
        </div>

        <div class="cards">
            <div class="card"><h2>{money(total_debt)}</h2><p>Total debt</p></div>
            <div class="card"><h2>{money(total_paid)}</h2><p>Total paid</p></div>
            <div class="card"><h2>{money(remaining)}</h2><p>Remaining</p></div>
        </div>

        <h2>Payment Timeline</h2>

        <table>
            <thead>
                <tr>
                    <th>Type</th>
                    <th>Amount</th>
                    <th>Note</th>
                    <th>Date</th>
                </tr>
            </thead>
            <tbody>
                {payment_rows or "<tr><td colspan='4'>No payments recorded yet.</td></tr>"}
            </tbody>
        </table>
    </body>
    </html>
    """

    return html


@router.post("/dashboard/remind/{debt_id}")
def dashboard_remind(
    request: Request,
    debt_id: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        ok, error = send_payment_reminder(
            debt.creditor_name,
            debt.phone_number,
            amount,
        )

        if ok:
            return RedirectResponse("/dashboard?success=sent", status_code=303)

    return RedirectResponse("/dashboard?error=send_failed", status_code=303)


@router.post("/dashboard/pay/{debt_id}")
def dashboard_pay(
    request: Request,
    debt_id: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if debt and debt.phone_number and debt.balance_cents > 0:
        amount = debt.balance_cents // 100
        ok, error = send_payment_link(
            debt.creditor_name,
            debt.phone_number,
            amount,
        )

        if ok:
            return RedirectResponse("/dashboard?success=sent", status_code=303)

    return RedirectResponse("/dashboard?error=send_failed", status_code=303)


@router.post("/dashboard/paid/{debt_id}")
def dashboard_paid(
    request: Request,
    debt_id: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if debt:
        amount = debt.balance_cents // 100

        if debt.phone_number and amount > 0:
            send_payment_received(
                debt.creditor_name,
                debt.phone_number,
                amount,
            )

        payment = Payment(
            user_id=current_user.id,
            debt_id=debt.id,
            amount_cents=debt.balance_cents,
            note="Marked as paid",
        )

        debt.balance_cents = 0

        db.add(payment)
        db.add(debt)
        db.commit()

    return RedirectResponse("/dashboard?success=paid", status_code=303)


@router.post("/dashboard/delete/{debt_id}")
def dashboard_delete(
    request: Request,
    debt_id: int,
    db: Session = Depends(get_db),
):
    current_user = get_current_user(request, db)

    if not current_user:
        return RedirectResponse("/login", status_code=303)

    debt = db.query(Debt).filter(
        Debt.id == debt_id,
        Debt.user_id == current_user.id,
    ).first()

    if debt:
        db.delete(debt)
        db.commit()

    return RedirectResponse("/dashboard?success=deleted", status_code=303)