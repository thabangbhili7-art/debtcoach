from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
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
    os.getenv("TWILIO_AUTH_TOKEN"),
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
    except Exception:
        return None


def make_response(reply: str):
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Message>{escape(reply)}</Message></Response>"
    )
    return PlainTextResponse(content=xml, media_type="application/xml")


def normalize_phone(phone: str):
    phone = (phone or "").strip().replace(" ", "")

    if phone.startswith("0"):
        phone = "+27" + phone[1:]

    return phone


def reminder_message(customer_name: str, amount_rands: int):
    return (
        f"Hi {customer_name}, this is a friendly reminder that you have "
        f"an outstanding balance of R{amount_rands}. "
        "Please let us know once payment is made."
    )


def send_whatsapp(to: str, message: str):
    to = normalize_phone(to)

    try:
        twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{to}",
            body=message,
        )
        return True, None
    except Exception as e:
        print("TWILIO SEND ERROR:", str(e))
        return False, str(e)


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
    if text.lower() in {"hi", "hello", "hey", "start"}:
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
        if text.lower() in {"yes", "y"}:
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
        upper_text = text.upper()

        # ADD
        if upper_text == "ADD":
            set_step(db, db_user.id, "add_name")
            return make_response("Send customer name.")

        # LIST
        if upper_text in {"LIST", "DEBTS"}:
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers yet.")

            lines = []
            total = 0

            for d in debts:
                amt = d.balance_cents // 100
                total += amt
                phone_display = d.phone_number or "No phone"
                lines.append(f"• {d.creditor_name} – R{amt} ({phone_display})")

            lines.append(f"\nTotal owed: R{total}")
            return make_response("\n".join(lines))

        # SUMMARY
        if upper_text == "SUMMARY":
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No data yet.")

            total = sum(d.balance_cents for d in debts) // 100
            count = len(debts)

            return make_response(
                f"Customers owe you R{total} across {count} account(s)."
            )

        # RESET
        if upper_text == "RESET":
            db.query(Debt).filter(Debt.user_id == db_user.id).delete()
            db.commit()
            set_step(db, db_user.id, "business_ready")
            return make_response("All customer data cleared.")

        # -------------------------
        # REMIND LOGIC
        # -------------------------
        if upper_text.startswith("REMIND"):
            command = text[6:].strip()

            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers to remind.")

            if not command:
                return make_response(
                    "Use:\nREMIND John\nREMIND John, Tshepo\nREMIND ALL"
                )

            # REMIND ALL
            if command.upper() == "ALL":
                sent = []
                failed = []
                skipped = []

                for d in debts:
                    if d.balance_cents <= 0:
                        skipped.append(d.creditor_name)
                        continue

                    if not d.phone_number:
                        failed.append(f"{d.creditor_name} (no phone)")
                        continue

                    amount = d.balance_cents // 100
                    ok, error = send_whatsapp(
                        d.phone_number,
                        reminder_message(d.creditor_name, amount),
                    )

                    if ok:
                        sent.append(d.creditor_name)
                    else:
                        failed.append(d.creditor_name)

                reply_parts = []

                if sent:
                    reply_parts.append(f"Sent to: {', '.join(sent)}.")
                if failed:
                    reply_parts.append(f"Failed/skipped: {', '.join(failed)}.")
                if not sent and not failed:
                    reply_parts.append("No reminders sent.")

                return make_response("\n".join(reply_parts))

            # REMIND ONE OR MULTIPLE
            requested_names = [n.strip().lower() for n in command.split(",") if n.strip()]

            sent = []
            not_found = []
            failed = []

            for name in requested_names:
                match = None

                for d in debts:
                    if name in (d.creditor_name or "").lower():
                        match = d
                        break

                if not match:
                    not_found.append(name)
                    continue

                if not match.phone_number:
                    failed.append(f"{match.creditor_name} (no phone)")
                    continue

                amount = match.balance_cents // 100
                ok, error = send_whatsapp(
                    match.phone_number,
                    reminder_message(match.creditor_name, amount),
                )

                if ok:
                    sent.append(match.creditor_name)
                else:
                    failed.append(match.creditor_name)

            reply_parts = []

            if sent:
                reply_parts.append(f"Sent to: {', '.join(sent)}.")
            if failed:
                reply_parts.append(f"Failed: {', '.join(failed)}.")
            if not_found:
                reply_parts.append(f"Not found: {', '.join(not_found)}.")

            return make_response(
                "\n".join(reply_parts) if reply_parts else "No reminders sent."
            )

        return make_response(
            "Commands:\nADD\nLIST\nSUMMARY\nREMIND <name>\nREMIND John, Tshepo\nREMIND ALL"
        )

    # -------------------------
    # ADD FLOW
    # -------------------------
    if step == "add_name":
        update_scratch(db, db_user.id, name=text)
        set_step(db, db_user.id, "add_phone")
        return make_response("Send phone number (e.g. +27712345678).")

    if step == "add_phone":
        clean_phone = normalize_phone(text)
        update_scratch(db, db_user.id, phone=clean_phone)
        set_step(db, db_user.id, "add_amount")
        return make_response("Send amount owed.")

    if step == "add_amount":
        amount = parse_amount(text)

        if amount is None or amount <= 0:
            return make_response("Send a valid amount.")

        scratch = get_scratch(db, db_user.id)
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

        update_scratch(db, db_user.id, name=None, phone=None)
        set_step(db, db_user.id, "business_ready")

        return make_response(
            f"Added {name} – owes you R{amount}.\nReply ADD to add another."
        )

    return make_response("Say HI to start.")




