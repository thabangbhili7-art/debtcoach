from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
import re
import os
import json
from html import escape
from twilio.rest import Client

from ..db import get_db
from ..state_db import get_step, set_step, get_scratch, update_scratch
from ..models import User, Debt

router = APIRouter()

twilio_client = Client(
    os.getenv("TWILIO_ACCOUNT_SID"),
    os.getenv("TWILIO_AUTH_TOKEN"),
)

TWILIO_WHATSAPP_NUMBER = "whatsapp:+12312725816"
PAYMENT_LINK = os.getenv("PAYMENT_LINK", "https://debtcoach.online/pay")

PAYMENT_REMINDER_SID = "HX63157ef79d57913569521535e396af35"
FINAL_REMINDER_SID = "HXba133d6940bfef28577e385005c4cf92"
PAYMENT_LINK_SID = "HXacc4980c80ab5f0a1fca7cb01221e5eb"
CONSENT_REQUEST_SID = "HXce82ce3a4b0f032d6f0a120c076920e6"
DEBT_CONSENT_SID = "HX054b382f7b22aae4159cc83b05cbf2a4"
PAYMENT_RECEIVED_SID = "HX2871dd1654529f46283a791d9767dd0c"

AMOUNT_RE = re.compile(r"(?i)\b(?:r\s*)?(\d[\d\s,\.]*)\b")

VALID_SA_MOBILE_PREFIXES = {
    "60", "61", "62", "63", "64", "65", "66", "67", "68",
    "71", "72", "73", "74", "76", "78", "79",
    "81", "82", "83", "84",
}


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

    if not phone:
        return None

    if phone.startswith("0"):
        phone = "+27" + phone[1:]

    if not phone.startswith("+27"):
        return None

    digits = phone[3:]

    if len(digits) != 9:
        return None

    if digits[:2] not in VALID_SA_MOBILE_PREFIXES:
        return None

    return phone


def send_template(to: str, content_sid: str, variables: dict):
    clean_to = normalize_phone(to)

    if not clean_to:
        return False, "Invalid phone number"

    try:
        msg = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{clean_to}",
            content_sid=content_sid,
            content_variables=json.dumps(variables),
        )
        print("TWILIO TEMPLATE SID:", msg.sid)
        return True, None
    except Exception as e:
        print("TWILIO TEMPLATE ERROR:", str(e))
        return False, str(e)


def send_whatsapp(to: str, message: str):
    clean_to = normalize_phone(to)

    if not clean_to:
        return False, "Invalid phone number"

    try:
        msg = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=f"whatsapp:{clean_to}",
            body=message,
        )
        print("TWILIO MESSAGE SID:", msg.sid)
        return True, None
    except Exception as e:
        print("TWILIO SEND ERROR:", str(e))
        return False, str(e)


def send_payment_reminder(name: str, phone: str, amount: int):
    return send_template(
        phone,
        PAYMENT_REMINDER_SID,
        {
            "1": name,
            "2": str(amount),
        },
    )


def send_final_reminder(name: str, phone: str, amount: int):
    return send_template(
        phone,
        FINAL_REMINDER_SID,
        {
            "1": name,
            "2": str(amount),
        },
    )


def send_payment_link(name: str, phone: str, amount: int):
    return send_template(
        phone,
        PAYMENT_LINK_SID,
        {
            "1": name,
            "2": str(amount),
        },
    )


def send_payment_received(name: str, phone: str, amount: int):
    return send_template(
        phone,
        PAYMENT_RECEIVED_SID,
        {
            "1": name,
            "2": str(amount),
        },
    )


def reminder_message(customer_name: str, amount_rands: int):
    return (
        f"Hi {customer_name}, this is a friendly reminder that you have "
        f"an outstanding balance of R{amount_rands}. "
        "Please reply once payment is made."
    )


def payment_message(customer_name: str, amount_rands: int):
    return (
        f"Hi {customer_name},\n\n"
        f"You have an outstanding balance of R{amount_rands}.\n\n"
        f"Please complete payment here:\n{PAYMENT_LINK}\n\n"
        "Thank you."
    )


def find_debt_by_name(debts, name: str):
    name = (name or "").strip().lower()

    for d in debts:
        if name in (d.creditor_name or "").lower():
            return d

    return None


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    data = await request.form()

    text = str(data.get("Body") or "").strip()
    phone = str(data.get("From") or "").replace("whatsapp:", "").strip()

    db_user = db.query(User).filter(User.phone_e164 == phone).one_or_none()

    if not db_user:
        db_user = User(phone_e164=phone)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

    step = get_step(db, db_user.id)

    if text.lower() in {"hi", "hello", "hey", "start"}:
        set_step(db, db_user.id, "consent")
        return make_response(
            "Hi 👋 I’m DebtCoach AI.\n\n"
            "I help businesses track customer debts, send reminders, and collect payments on WhatsApp.\n\n"
            "Do you want to continue?"
        )

    if step == "consent":
        if text.lower() in {"yes", "y"}:
            set_step(db, db_user.id, "business_ready")
            return make_response(
                "You're set.\n\n"
                "Commands:\n"
                "ADD - add a customer\n"
                "LIST - view customers\n"
                "SUMMARY - total owed\n"
                "REMIND John - send reminder\n"
                "REMIND ALL - remind everyone\n"
                "PAY John - send payment link"
            )

        return make_response("Reply YES to continue.")

    if step == "business_ready":
        upper_text = text.upper()

        if upper_text == "ADD":
            set_step(db, db_user.id, "add_name")
            return make_response("Send customer name.")

        if upper_text in {"LIST", "DEBTS"}:
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers yet.")

            lines = []
            total = 0

            for d in debts:
                amount = d.balance_cents // 100
                total += amount
                phone_display = d.phone_number or "No phone"
                lines.append(f"• {d.creditor_name} – R{amount} ({phone_display})")

            lines.append(f"\nTotal owed: R{total}")
            return make_response("\n".join(lines))

        if upper_text == "SUMMARY":
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No data yet.")

            total = sum(d.balance_cents for d in debts) // 100
            count = len(debts)

            return make_response(
                f"Customers owe you R{total} across {count} account(s)."
            )

        if upper_text == "RESET":
            db.query(Debt).filter(Debt.user_id == db_user.id).delete()
            db.commit()
            set_step(db, db_user.id, "business_ready")
            return make_response("All customer data cleared.")

        if upper_text.startswith("PAY"):
            command = text[3:].strip()

            if not command:
                return make_response("Use:\nPAY John")

            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()
            match = find_debt_by_name(debts, command)

            if not match:
                return make_response(f"No customer found for '{command}'.")

            if not match.phone_number:
                return make_response(f"{match.creditor_name} has no phone number saved.")

            amount = match.balance_cents // 100
            ok, error = send_payment_link(match.creditor_name, match.phone_number, amount)

            if ok:
                return make_response(f"Payment link sent to {match.creditor_name}.")

            return make_response(f"Failed to send payment link: {error}")

        if upper_text.startswith("REMIND"):
            command = text[6:].strip()
            debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()

            if not debts:
                return make_response("No customers to remind.")

            if not command:
                return make_response("Use:\nREMIND John\nREMIND John, Tshepo\nREMIND ALL")

            if command.upper() == "ALL":
                sent = []
                failed = []

                for d in debts:
                    if d.balance_cents <= 0:
                        continue

                    if not d.phone_number:
                        failed.append(f"{d.creditor_name} (no phone)")
                        continue

                    amount = d.balance_cents // 100
                    ok, error = send_payment_reminder(
                        d.creditor_name,
                        d.phone_number,
                        amount,
                    )

                    if ok:
                        sent.append(d.creditor_name)
                    else:
                        failed.append(f"{d.creditor_name} ({error})")

                reply_parts = []

                if sent:
                    reply_parts.append(f"Sent to: {', '.join(sent)}.")
                if failed:
                    reply_parts.append(f"Failed/skipped: {', '.join(failed)}.")
                if not sent and not failed:
                    reply_parts.append("No reminders sent.")

                return make_response("\n".join(reply_parts))

            requested_names = [n.strip().lower() for n in command.split(",") if n.strip()]
            sent = []
            not_found = []
            failed = []

            for name in requested_names:
                match = find_debt_by_name(debts, name)

                if not match:
                    not_found.append(name)
                    continue

                if not match.phone_number:
                    failed.append(f"{match.creditor_name} (no phone)")
                    continue

                amount = match.balance_cents // 100
                ok, error = send_payment_reminder(
                    match.creditor_name,
                    match.phone_number,
                    amount,
                )

                if ok:
                    sent.append(match.creditor_name)
                else:
                    failed.append(f"{match.creditor_name} ({error})")

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
            "Commands:\n"
            "ADD - add a customer\n"
            "LIST - view customers\n"
            "SUMMARY - total owed\n"
            "REMIND John - send reminder\n"
            "REMIND ALL - remind everyone\n"
            "PAY John - send payment link"
        )

    if step == "add_name":
        update_scratch(db, db_user.id, name=text)
        set_step(db, db_user.id, "add_phone")
        return make_response("Send phone number, e.g. +27712345678 or 0712345678.")

    if step == "add_phone":
        clean_phone = normalize_phone(text)

        if not clean_phone:
            return make_response(
                "Invalid phone number. Use a valid South African mobile number, e.g. +27712345678 or 0712345678."
            )

        update_scratch(db, db_user.id, phone=clean_phone)
        set_step(db, db_user.id, "add_amount")
        return make_response("Send amount owed.")

    if step == "add_amount":
        amount = parse_amount(text)

        if amount is None or amount <= 0:
            return make_response("Send a valid amount greater than 0.")

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




