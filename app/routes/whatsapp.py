from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
import re

from ..db import get_db
from ..state import get_step, set_step, get_scratch, update_scratch
from ..models import User, Debt, Payment
from html import escape 
from fastapi.responses import JSONResponse, PlainTextResponse


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
    If is_twilio=True → return TwiML XML so Twilio sends the WhatsApp message.
    Else → return JSON (for curl / local testing).
    """
    if is_twilio:
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response><Message>{escape(reply)}</Message></Response>"
        )
        return PlainTextResponse(content=xml, media_type="application/xml")
    else:
        return JSONResponse({"reply": reply})


@router.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    # 1) Get payload
    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = dict(form)

    text = str(data.get("text") or data.get("Body") or data.get("message") or "").strip()
    phone = str(data.get("from") or data.get("From") or "unknown").strip()
    # Detect Twilio-style requests (form-encoded, From/Body fields)
    is_twilio = (
        ("Body" in data) or
        ("From" in data and str(data["From"]).startswith("whatsapp:"))
    )


    # 2) Ensure user exists in DB (for foreign key on debts)
    db_user = db.query(User).filter(User.phone_e164 == phone).one_or_none()
    if not db_user:
        db_user = User(phone_e164=phone)
        db.add(db_user)
        db.commit()
        db.refresh(db_user)

    # 3) Use in-memory state keyed by phone number
    step = get_step(phone)
    scratch = get_scratch(phone)

   #THIS BLOCK RIGHT HERE (before PAID/DEBTS/RESET/SUMMARY) overvides
    greet = text.strip().lower()
    if greet in {"hi", "hello", "hey", "hie"}:
        set_step(phone, "consent")
        update_scratch(
            phone,
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


    # 🔹 Global PAID command: log a payment and reduce debts
    if text.upper().startswith("PAID"):
        amount = parse_amount(text)
        if amount is None:
            reply = "Please tell me how much you paid, e.g. 'PAID 500' or 'PAID R 750'."
            return make_response(reply, is_twilio)

        pay_cents = amount * 100

        # fetch debts in simple order (snowball style by id)
        debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id, Debt.balance_cents > 0)
              .order_by(Debt.id.asc())
              .all()
        )
        if not debts:
            reply = "I don't have any open debts for you. Send DEBTS to see what I have on file."
            return make_response(reply, is_twilio)

        remaining = pay_cents
        for d in debts:
            if remaining <= 0:
                break
            if d.balance_cents <= remaining:
                # fully pay this debt
                remaining -= d.balance_cents
                d.balance_cents = 0
            else:
                # partially pay this debt
                d.balance_cents -= remaining
                remaining = 0
            db.add(d)

        # log payment
        payment = Payment(user_id=db_user.id, amount_cents=pay_cents)
        db.add(payment)
        db.commit()

        # build reply with new balances
        updated_debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id)
              .order_by(Debt.id.asc())
              .all()
        )
        lines = []
        total_cents = 0
        for d in updated_debts:
            total_cents += d.balance_cents
            rands = d.balance_cents // 100
            cents = d.balance_cents % 100
            if cents:
                amount_str = f"R{rands}.{cents:02d}"
            else:
                amount_str = f"R{rands}"
            lines.append(f"• {d.creditor_name} – {amount_str}")

        # ⬇NEW: recalc payoff estimate for SUMMARY
        remaining_total_rands = total_cents // 100
        budget = scratch.get("budget")   # scratch came from get_scratch(phone) at top

        if budget:
            new_months = max(1, round(remaining_total_rands / budget))
            update_scratch(phone, total=remaining_total_rands, months=new_months)
        #END NEW 

        total_rands = total_cents // 100
        reply = (
            f"Nice! I logged your payment of R{amount}.\n"
            f"Your updated debts are:\n" + "\n".join(lines) +
            f"\nTotal remaining: R{total_rands}"
        )
        return make_response(reply, is_twilio)

    # 🔹 Global command: show current debts
    if text.upper() == "DEBTS":
        debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id)
              .order_by(Debt.id.asc())
              .all()
        )
        if not debts:
            
            reply = "I don't have any debts saved for you yet. Add creditors first, then I'll store them."
            return make_response(reply, is_twilio)
        
        lines = []
        for d in debts:
            rands = d.balance_cents // 100
            cents = d.balance_cents % 100
            if cents:
                amount_str = f"R{rands}.{cents:02d}"
            else:
                amount_str = f"R{rands}"
            lines.append(f"• {d.creditor_name} – {amount_str}")

        reply = "Here’s what I have for you:\n" + "\n".join(lines)
        return make_response(reply, is_twilio)

    # 🔹 Global RESET command
    if text.upper() == "RESET":
        # wipe DB debts + payments
        db.query(Debt).filter(Debt.user_id == db_user.id).delete()
        db.query(Payment).filter(Payment.user_id == db_user.id).delete()

        # wipe in-memory convo + scratch
        update_scratch(phone, creditors=[], balance_index=None, budget=None, total=None, months=None)
        set_step(phone, "start")

        db.commit()

        
        reply = "All your debt data was cleared. Say HI to start again."
        return make_response(reply, is_twilio)
        

    # 🔹 Global SUMMARY command
    if text.upper() == "SUMMARY":
        debts = (
            db.query(Debt)
              .filter(Debt.user_id == db_user.id)
              .all()
        )
        if not debts:
            reply = "I don’t have any debts saved for you yet. Say HI to start or send DEBTS to see details."
            return make_response(reply, is_twilio)

        total_cents = sum(d.balance_cents for d in debts)
        total_rands = total_cents // 100
        num_debts = len(debts)

        # budget was stored in scratch during the BUDGET step
        budget = scratch.get("budget")

        if budget:
            # 👇 recompute months based on current remaining total
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


    # STEP: start → ask consent
    if step == "start":
        set_step(phone, "consent")
        reply = (
                "Hi! I’m DebtCoach. I help you organise debts.\n"
                "Do you consent to me processing your debt info to create a plan and send reminders?\n"
                "Reply YES or NO."
            )
        return make_response(reply, is_twilio)

    # STEP: consent
    if step == "consent":
        msg = text.lower()
        if msg in {"yes", "y", "yeah", "yebo", "ewe", "ee"}:
            set_step(phone, "intake_creditor")
            update_scratch(phone, creditors=[], balance_index=None)
            reply = "Great! Who do you owe first? (Type one creditor at a time, or type DONE to finish)"
            return make_response(reply, is_twilio)

    # STEP: intake_creditor
    if step == "intake_creditor":
        if text.lower() == "done":
            creditors = scratch.get("creditors", [])
            if not creditors:
                return JSONResponse({"reply": "Add at least one creditor name, then type DONE."})

            # start asking balances from the *first* creditor
            update_scratch(phone, balance_index=0)
            set_step(phone, "intake_balance")
            first_name = creditors[0]["name"]
            reply = f"Nice. What is the current balance for {first_name}? (e.g. 1200 or R 1,200)"
            return make_response(reply, is_twilio)
            

        # otherwise, treat text as a new creditor name
        creditors = scratch.get("creditors", [])

        # 🔹 NEW: limit number of creditors to 20
        if len(creditors) >= 20:
            reply  ="Let’s keep it manageable. You’ve added 20 creditors already.\nType DONE if you’re finished, or RESET to start over."
            return make_response(reply, is_twilio)
        creditors.append({"name": text, "balance": None})
        update_scratch(phone, creditors=creditors)
        reply = f"Added {text}. You can add another creditor, or type DONE."
        return make_response(reply, is_twilio)



    
    # STEP: intake_balance (for current creditor by index)
    if step == "intake_balance":
        amt = parse_amount(text)
        if amt is None:
            return JSONResponse({"reply": "Please send the balance as a number (e.g. 1200 or R 1,200)."})

        if amt <= 0:
            return JSONResponse({"reply": "The balance must be more than zero. Please send a valid amount."})
        if amt > 1_000_000:
            
            reply = "That amount seems very high. If it’s correct, please split this creditor into separate accounts or confirm with a counsellor."
            return make_response(reply, is_twilio)
           
        creditors = scratch.get("creditors", [])
        idx = scratch.get("balance_index", 0)

        # safety check
        if idx < 0 or idx >= len(creditors):
            # something went weird — restart balance collection
            update_scratch(phone, balance_index=0)
            set_step(phone, "intake_balance")
            first_name = creditors[0]["name"]
            
            reply = f"Let’s try again. What is the balance for {first_name}?"
            return make_response(reply, is_twilio)
           

        # set balance for current creditor
        creditors[idx]["balance"] = amt
        update_scratch(phone, creditors=creditors)

        # if there is another creditor, ask for next one
        if idx + 1 < len(creditors):
            next_idx = idx + 1
            next_name = creditors[next_idx]["name"]
            update_scratch(phone, balance_index=next_idx)
            reply = f"Got it. Now what is the balance for {next_name}?"
            return make_response(reply, is_twilio)
           

        # no more creditors: move to budget step
        update_scratch(phone, balance_index=None)
        set_step(phone, "budget")
        
        reply = "Thanks. How much can you pay each month across all debts? (numbers only, e.g. 1500)"
        return make_response(reply, is_twilio)
        


    # STEP: budget
    if step == "budget":
        budget = parse_amount(text)
        if budget is None:
            return JSONResponse({"reply": "Please send the monthly amount as a number (e.g. 1500)."})

        if budget < 100:
            return JSONResponse({
                "reply": "An amount under R100/month is very low. Please send a realistic monthly amount you can commit."
            })
        if budget > 100_000:
            
            reply = "That monthly amount seems very high. Please double-check and send again."
            return make_response(reply, is_twilio)
            

        creditors = scratch.get("creditors", [])
        total = sum(c.get("balance") or 0 for c in creditors)
        months = max(1, round(total / budget)) if budget else 1

        for c in creditors:
            db_debt = Debt(
                user_id=db_user.id,
                creditor_name=c["name"],
                balance_cents=(c.get("balance") or 0) * 100,
            )
            db.add(db_debt)
        db.commit()

        update_scratch(phone, budget=budget, total=total, months=months)
        set_step(phone, "plan_ready")

        
        reply = f"If you pay R{budget} per month, you can be debt-free in ~{months} months.\nType START to restart, or PAID after you make a payment."
        return make_response(reply, is_twilio)

    # STEP: plan_ready
    if step == "plan_ready":
        if text.lower() == "start":
            set_step(phone, "intake_creditor")
            update_scratch(phone, creditors=[])
            reply = "Ok, add creditors again. Type one at a time, or DONE when finished."
            return make_response(reply, is_twilio)
        reply= "All set. Say START to restart, or send DEBTS / PAID <amount> anytime."
        return make_response(reply, is_twilio)



