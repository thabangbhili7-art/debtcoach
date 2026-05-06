from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session
import re
from html import escape
from twilio.rest import Client
import os

from ..db import get_db
from ..state_db import get_step, set_step, get_scratch, update_scratch
from ..models import User, Debt

router = APIRouter()

# -------------------------
# TWILIO CONFIG
# -------------------------
twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN")
)

TWILIO_WHATSAPP_NUMBER = "whatsapp:+12312725816"

# -------------------------
# HELPERS
# -------------------------
AMOUNT_RE = re.compile(r"(?i)\b(?:r\s*)?(\d[\d\s,\.]*)\b")

def parse_amount(text: str):
    m = AMOUNT_RE.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(",", "")
    try:
        return int(float(raw))
    except:
        return None


def make_response(reply: str):
    xml = f'<?xml version="1.0"?><Response><Message>{escape(reply)}</Message></Response>'
    return PlainTextResponse(content=xml, media_type="application/xml")


def send_whatsapp(to, message):
    twilio_client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=f"whatsapp:{to}",
        body=message
    )


# -------------------------
# MAIN WEBHOOK
# -------------------------
@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):

    data = await request.form()

    text = str(data.get("Body") or "").strip()
    phone = str(data.get("From") or "").replace("whatsapp:", "").strip()

    # -------------------------
    # USER
    # -------------------------
    db_user = db.query(User).filter(User.phone_e164 == phone).one_or_none()

    if not db_user:
        db_user = User(phone_e164=phone)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

    step = get_step(db, db_user.id)
    scratch = get_scratch(db, db_user.id)

    # -------------------------
    # GREETING
    # -------------------------
    if text.lower() in {"hi", "hello", "start"}:
        set_step(db, db_user.id, "consent")

        return make_response(
            "Hi! I’m DebtCoach AI for businesses.\n"
            "I help you track customers who owe you and send reminders.\n\n"
            "Reply YES to continue."
        )

    # -------------------------
    # CONSENT
    # -------------------------
    if step == "consent":
        if text.lower() == "yes":
            set_step(db, db_user.id, "business_ready")

            return make_response(
                "You're set.\n\n"
                "Commands:\n"
                "ADD\n"
                "LIST\n"
                "SUMMARY\n"
                "REMIND <name>\n"
                "REMIND John, Tshepo\n"
                "REMIND ALL"
            )

        return make_response("Reply YES to continue.")

    # -------------------------
    # MAIN MODE
    # -------------------------
    if step == "business_ready":

        # ADD
        if text.upper() == "ADD":
            set_step(db, db_user.id, "add_name")
            return make_response("Send customer name.")

        # LIST
        if text.upper() in {"LIST", "DEBTS"}:
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers yet.")

            lines = []
            for d in debts:
                amt = d.balance_cents // 100
                lines.append(f"• {d.creditor_name} – R{amt} ({d.phone_number})")

            return make_response("\n".join(lines))

        # SUMMARY
        if text.upper() == "SUMMARY":
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No data yet.")

            total = sum(d.balance_cents for d in debts) // 100

            return make_response(f"Customers owe you R{total}.")

        # -------------------------
        # REMIND LOGIC (FULL FLEX)
        # -------------------------
        if text.upper().startswith("REMIND"):

            command = text[6:].strip()

            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers to remind.")

            # GUIDE USER
            if not command:
                return make_response(
                    "Use:\nREMIND John\nREMIND John, Tshepo\nREMIND ALL"
                )

            # REMIND ALL
            if command.upper() == "ALL":
                sent = 0

                for d in debts:
                    if d.phone_number and d.balance_cents > 0:
                        send_whatsapp(
                            d.phone_number,
                            f"Hi {d.creditor_name}, reminder you owe R{d.balance_cents // 100}."
                        )
                        sent += 1

                return make_response(f"Sent reminders to {sent} customers.")

            # REMIND MULTIPLE
            names = [n.strip().lower() for n in command.split(",")]

            sent = []
            not_found = []

            for name in names:
                match = None

                for d in debts:
                    if name in d.creditor_name.lower():
                        match = d
                        break

                if match and match.phone_number:
                    send_whatsapp(
                        match.phone_number,
                        f"Hi {match.creditor_name}, reminder you owe R{match.balance_cents // 100}."
                    )
                    sent.append(match.creditor_name)
                else:
                    not_found.append(name)

            reply = ""

            if sent:
                reply += f"Sent to: {', '.join(sent)}.\n"

            if not_found:
                reply += f"Not found: {', '.join(not_found)}."

            return make_response(reply.strip())

    # -------------------------
    # ADD FLOW
    # -------------------------
    if step == "add_name":
        update_scratch(db, db_user.id, name=text)
        set_step(db, db_user.id, "add_phone")
        return make_response("Send phone number (e.g. +27712345678).")

    if step == "add_phone":
        update_scratch(db, db_user.id, phone=text)
        set_step(db, db_user.id, "add_amount")
        return make_response("Send amount owed.")

    if step == "add_amount":
        amount = parse_amount(text)

        if amount is None or amount <= 0:
            return make_response("Send a valid amount.")

        name = scratch.get("name")
        phone_num = scratch.get("phone")

        db_debt = Debt(
            user_id=db_user.id,
            creditor_name=name,
            phone_number=phone_num,
            balance_cents=amount * 100,
        )
        db.add(db_debt)
        db.commit()

        set_step(db, db_user.id, "business_ready")

        return make_response(
            f"Added {name} – owes you R{amount}.\nReply ADD to add another."
        )

    return make_response("Say HI to start.")




