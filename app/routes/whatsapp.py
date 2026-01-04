from fastapi import APIRouter, Request, Depends
from fastapi.responses import PlainTextResponse, JSONResponse
from sqlalchemy.orm import Session
import re
from html import escape

from ..db import get_db
from ..state_db import get_step, set_step, get_scratch, update_scratch
from ..models import User, Debt, Payment

router = APIRouter()

AMOUNT_RE = re.compile(r"(?i)\b(?:r\s*)?(\d[\d\s,\.]*)\b")

def parse_amount(text: str) -> int | None:
    s = (text or "").replace("\u00A0", " ").strip()
    m = AMOUNT_RE.search(s)
    if not m:
        return None
    raw = m.group(1).replace(" ", "").replace(",", "")
    try:
        return int(round(float(raw)))
    except Exception:
        return None

def make_response(reply: str, is_twilio: bool):
    """
    Twilio WhatsApp expects TwiML XML.
    Local curl/dev can use JSON.
    """
    if is_twilio:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Message>{escape(reply)}</Message></Response>"
        )
        return PlainTextResponse(content=xml, media_type="application/xml")
    return JSONResponse({"reply": reply})


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Parse incoming payload (Twilio sends form-encoded; curl sends JSON)
    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = dict(form)

    text = str(data.get("text") or data.get("Body") or data.get("message") or "").strip()

    raw_from = data.get("from") or data.get("From") or "unknown"
    phone = str(raw_from).strip()

    # Detect Twilio WhatsApp: From is usually like "whatsapp:+27..."
    is_twilio = ("Body" in data) or ("From" in data and str(data["From"]).startswith("whatsapp:"))

    # Normalize phone for DB (store without whatsapp: prefix)
    if phone.startswith("whatsapp:"):
        phone = phone.replace("whatsapp:", "").strip()

    # 2) Ensure user exists
    db_user = db.query(User).filter(User.phone_e164 == phone).one_or_none()
    if not db_user:
        db_user = User(phone_e164=phone)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

    # 3) Load persistent conversation state
    step = get_step(db, db_user.id)
    scratch = get_scratch(db, db_user.id)

    # -------------------------
    # GLOBAL: greetings reset
    # -------------------------
    greet = text.strip().lower()
    if greet in {"hi", "hello", "hey", "hie", "start"}:
        set_step(db, db_user.id, "consent")
        update_scratch(
            db,
            db_user.id,
            creditors=[],
            balance_index=None,
            budget=None,
            total=None,
            months=None,
        )
        reply = (
            "Hi! I’m DebtCoach. I help you organise debts.\n"
            "Do you consent to me processing your debt info to create a plan and send reminders?\n"
            "Reply YES or NO."
        )
        return make_response(reply, is_twilio)

    # -------------------------
    # GLOBAL: PAID <amount>
    # -------------------------
    if text.upper().startswith("PAID"):
        amount = parse_amount(text)
        if amount is None:
            return make_response(
                "Please tell me how much you paid, e.g. 'PAID 500' or 'PAID R 750'.",
                is_twilio,
            )

        pay_cents = amount * 100

        debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id, Debt.balance_cents > 0)
              .order_by(Debt.id.asc())
              .all()
        )
        if not debts:
            return make_response(
                "I don't have any open debts for you. Send DEBTS to see what I have on file.",
                is_twilio,
            )

        remaining = pay_cents
        for d in debts:
            if remaining <= 0:
                break
            if d.balance_cents <= remaining:
                remaining -= d.balance_cents
                d.balance_cents = 0
            else:
                d.balance_cents -= remaining
                remaining = 0
            db.add(d)

        payment = Payment(user_id=db_user.id, amount_cents=pay_cents)
        db.add(payment)
        db.commit()

        updated_debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id)
              .order_by(Debt.id.asc())
              .all()
        )

        total_cents = sum(d.balance_cents for d in updated_debts)

        # update scratch months/total based on remaining + budget if we have one
        budget = get_scratch(db, db_user.id).get("budget")
        remaining_total_rands = total_cents // 100
        if budget:
            new_months = max(1, round(remaining_total_rands / budget))
            update_scratch(db, db_user.id, total=remaining_total_rands, months=new_months)

        lines = []
        for d in updated_debts:
            rands = d.balance_cents // 100
            cents = d.balance_cents % 100
            amount_str = f"R{rands}.{cents:02d}" if cents else f"R{rands}"
            lines.append(f"• {d.creditor_name} – {amount_str}")

        reply = (
            f"Nice! I logged your payment of R{amount}.\n"
            f"Your updated debts are:\n" + "\n".join(lines) +
            f"\nTotal remaining: R{total_cents // 100}"
        )
        return make_response(reply, is_twilio)

    # -------------------------
    # GLOBAL: DEBTS
    # -------------------------
    if text.upper() == "DEBTS":
        debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id)
              .order_by(Debt.id.asc())
              .all()
        )
        if not debts:
            return make_response(
                "I don't have any debts saved for you yet. Say HI to start.",
                is_twilio,
            )

        lines = []
        for d in debts:
            rands = d.balance_cents // 100
            cents = d.balance_cents % 100
            amount_str = f"R{rands}.{cents:02d}" if cents else f"R{rands}"
            lines.append(f"• {d.creditor_name} – {amount_str}")

        return make_response("Here’s what I have for you:\n" + "\n".join(lines), is_twilio)

    # -------------------------
    # GLOBAL: RESET
    # -------------------------
    if text.upper() == "RESET":
        db.query(Debt).filter(Debt.user_id == db_user.id).delete()
        db.query(Payment).filter(Payment.user_id == db_user.id).delete()
        db.commit()

        update_scratch(
            db,
            db_user.id,
            creditors=[],
            balance_index=None,
            budget=None,
            total=None,
            months=None,
        )
        set_step(db, db_user.id, "start")

        return make_response("All your debt data was cleared. Say HI to start again.", is_twilio)

    # -------------------------
    # GLOBAL: SUMMARY
    # -------------------------
    if text.upper() == "SUMMARY":
        debts = db.query(Debt).filter(Debt.user_id == db_user.id).all()
        if not debts:
            return make_response(
                "I don’t have any debts saved for you yet. Say HI to start or send DEBTS to see details.",
                is_twilio,
            )

        total_cents = sum(d.balance_cents for d in debts)
        total_rands = total_cents // 100
        num_debts = len(debts)

        scratch = get_scratch(db, db_user.id)
        budget = scratch.get("budget")

        if budget:
            est_months = max(1, round(total_rands / budget))
            reply = (
                f"You currently owe R{total_rands} across {num_debts} debts.\n"
                f"With your current plan of R{budget}/month, you can be debt-free in ~{est_months} months.\n"
                "Send DEBTS for a detailed breakdown."
            )
        else:
            reply = (
                f"You currently owe R{total_rands} across {num_debts} debts.\n"
                "We don’t have a monthly plan yet. Say HI and go through the intake to set one up."
            )

        return make_response(reply, is_twilio)

    # -------------------------
    # FLOW: start -> consent
    # -------------------------
    if step == "start":
        set_step(db, db_user.id, "consent")
        reply = (
            "Hi! I’m DebtCoach. I help you organise debts.\n"
            "Do you consent to me processing your debt info to create a plan and send reminders?\n"
            "Reply YES or NO."
        )
        return make_response(reply, is_twilio)

    # -------------------------
    # FLOW: consent
    # -------------------------
    if step == "consent":
        msg = text.lower()
        if msg in {"yes", "y", "yeah", "yebo", "ewe", "ee", "sure", "ok"}:
            set_step(db, db_user.id, "intake_creditor")
            update_scratch(db, db_user.id, creditors=[], balance_index=None)
            return make_response(
                "Great! Who do you owe first? (Type one creditor at a time, or type DONE to finish)",
                is_twilio,
            )
        if msg in {"no", "n", "nope", "cha", "hayi", "aowa"}:
            set_step(db, db_user.id, "start")
            return make_response("No problem. If you change your mind, just say HI.", is_twilio)

        return make_response("Please reply YES to proceed, or NO to stop.", is_twilio)

    # -------------------------
    # FLOW: intake_creditor
    # -------------------------
    if step == "intake_creditor":
        if text.lower() == "done":
            creditors = scratch.get("creditors", [])
            if not creditors:
                return make_response("Add at least one creditor name, then type DONE.", is_twilio)

            update_scratch(db, db_user.id, balance_index=0)
            set_step(db, db_user.id, "intake_balance")

            first_name = creditors[0]["name"]
            return make_response(
                f"Nice. What is the current balance for {first_name}? (e.g. 1200 or R 1,200)",
                is_twilio,
            )

        creditors = scratch.get("creditors", [])
        if len(creditors) >= 20:
            return make_response(
                "Let’s keep it manageable. You’ve added 20 creditors already.\n"
                "Type DONE if you’re finished, or RESET to start over.",
                is_twilio,
            )

        creditors.append({"name": text, "balance": None})
        update_scratch(db, db_user.id, creditors=creditors)

        return make_response(f"Added {text}. You can add another creditor, or type DONE.", is_twilio)

    # -------------------------
    # FLOW: intake_balance
    # -------------------------
    if step == "intake_balance":
        amt = parse_amount(text)
        if amt is None:
            return make_response("Please send the balance as a number (e.g. 1200 or R 1,200).", is_twilio)

        if amt <= 0:
            return make_response("The balance must be more than zero. Please send a valid amount.", is_twilio)

        if amt > 1_000_000:
            return make_response(
                "That amount seems very high. If it’s correct, please split this creditor into separate accounts or confirm with a counsellor.",
                is_twilio,
            )

        creditors = scratch.get("creditors", [])
        idx = scratch.get("balance_index", 0)

        if not creditors:
            # should not happen, but recover gracefully
            set_step(db, db_user.id, "intake_creditor")
            update_scratch(db, db_user.id, creditors=[], balance_index=None)
            return make_response("Let’s restart. Who do you owe first?", is_twilio)

        if idx < 0 or idx >= len(creditors):
            update_scratch(db, db_user.id, balance_index=0)
            first_name = creditors[0]["name"]
            return make_response(f"Let’s try again. What is the balance for {first_name}?", is_twilio)

        creditors[idx]["balance"] = amt
        update_scratch(db, db_user.id, creditors=creditors)

        if idx + 1 < len(creditors):
            next_idx = idx + 1
            next_name = creditors[next_idx]["name"]
            update_scratch(db, db_user.id, balance_index=next_idx)
            return make_response(f"Got it. Now what is the balance for {next_name}?", is_twilio)

        # finished balances -> budget
        update_scratch(db, db_user.id, balance_index=None)
        set_step(db, db_user.id, "budget")
        return make_response(
            "Thanks. How much can you pay each month across all debts? (numbers only, e.g. 1500)",
            is_twilio,
        )

    # -------------------------
    # FLOW: budget
    # -------------------------
    if step == "budget":
        budget = parse_amount(text)
        if budget is None:
            return make_response("Please send the monthly amount as a number (e.g. 1500).", is_twilio)

        if budget < 100:
            return make_response(
                "An amount under R100/month is very low. Please send a realistic monthly amount you can commit.",
                is_twilio,
            )
        if budget > 100_000:
            return make_response("That monthly amount seems very high. Please double-check and send again.", is_twilio)

        creditors = scratch.get("creditors", [])
        total = sum(c.get("balance") or 0 for c in creditors)
        months = max(1, round(total / budget)) if budget else 1

        # Optional: clear old debts before re-saving intake (prevents duplicates)
        # If you want to keep old debts, comment these two lines out.
        db.query(Debt).filter(Debt.user_id == db_user.id).delete()
        db.commit()

        for c in creditors:
            db_debt = Debt(
                user_id=db_user.id,
                creditor_name=c["name"],
                balance_cents=(c.get("balance") or 0) * 100,
            )
            db.add(db_debt)
        db.commit()

        update_scratch(db, db_user.id, budget=budget, total=total, months=months)
        set_step(db, db_user.id, "plan_ready")

        return make_response(
            f"If you pay R{budget} per month, you can be debt-free in ~{months} months.\n"
            "Type START to restart, or PAID <amount> after you make a payment.",
            is_twilio,
        )

    # -------------------------
    # FLOW: plan_ready
    # -------------------------
    if step == "plan_ready":
        if text.lower() == "start":
            set_step(db, db_user.id, "intake_creditor")
            update_scratch(db, db_user.id, creditors=[], balance_index=None)
            return make_response(
                "Ok, add creditors again. Type one at a time, or DONE when finished.",
                is_twilio,
            )

        return make_response("All set. Say START to restart, or send DEBTS / PAID <amount> anytime.", is_twilio)

    # fallback
    set_step(db, db_user.id, "start")
    return make_response("Let’s begin. Say HI.", is_twilio)




