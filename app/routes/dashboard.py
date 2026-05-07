from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User, Debt

router = APIRouter()


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    debts = db.query(Debt).all()

    total_cents = sum(d.balance_cents for d in debts)
    total_rands = total_cents // 100
    total_customers = len(debts)
    with_phone = len([d for d in debts if d.phone_number])

    rows = ""

    for d in debts:
        amount = d.balance_cents // 100
        phone = d.phone_number or "No phone"

        rows += f"""
        <tr>
            <td>{d.creditor_name}</td>
            <td>{phone}</td>
            <td>R{amount}</td>
            <td>
                <a class="btn" href="/dashboard/remind/{d.id}">Remind</a>
                <a class="btn pay" href="/dashboard/pay/{d.id}">Pay Link</a>
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
                margin-bottom: 10px;
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
                margin: 0;
                font-size: 32px;
            }}

            .card p {{
                color: #94a3b8;
                margin-bottom: 0;
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
                text-align: left;
                border-bottom: 1px solid #334155;
            }}

            th {{
                background: #111827;
                color: #cbd5e1;
            }}

            .btn {{
                padding: 8px 12px;
                background: #2563eb;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                margin-right: 6px;
                font-size: 14px;
            }}

            .pay {{
                background: #16a34a;
            }}
        </style>
    </head>

    <body>
        <h1>DebtCoach Dashboard</h1>
        <div class="subtitle">Business collections overview</div>

        <div class="cards">
            <div class="card">
                <h2>R{total_rands}</h2>
                <p>Total owed</p>
            </div>

            <div class="card">
                <h2>{total_customers}</h2>
                <p>Customers</p>
            </div>

            <div class="card">
                <h2>{with_phone}</h2>
                <p>Reachable by WhatsApp</p>
            </div>
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
            <tbody>
                {rows}
            </tbody>
        </table>
    </body>
    </html>
    """

    return html