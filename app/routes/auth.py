import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from ..db import get_db
from ..models import User
from .whatsapp import normalize_phone

router = APIRouter()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str):
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str):
    return pwd_context.verify(password, password_hash)


def get_current_user(request: Request, db: Session):
    user_id = request.cookies.get("user_id")

    if not user_id:
        return None

    try:
        return db.query(User).filter(User.id == int(user_id)).first()
    except Exception:
        return None


AUTH_STYLES = """
<style>
body{
    margin:0;
    padding:0;
    background:#0f172a;
    font-family:Arial, sans-serif;
    color:white;
}

.container{
    width:100%;
    min-height:100vh;
    display:flex;
    justify-content:center;
    align-items:center;
}

.card{
    background:#1e293b;
    padding:40px;
    border-radius:20px;
    width:390px;
    border:1px solid #334155;
    box-shadow:0 0 30px rgba(0,0,0,0.35);
}

h1{
    margin-top:0;
    font-size:34px;
}

p{
    color:#94a3b8;
}

input{
    width:100%;
    padding:14px;
    margin-top:12px;
    border-radius:10px;
    border:1px solid #334155;
    background:#0f172a;
    color:white;
    font-size:16px;
    box-sizing:border-box;
}

button{
    width:100%;
    padding:14px;
    margin-top:20px;
    border:none;
    border-radius:10px;
    background:#22c55e;
    color:white;
    font-size:16px;
    font-weight:bold;
    cursor:pointer;
}

button:hover{
    opacity:0.9;
}

a{
    color:#93c5fd;
    text-decoration:none;
}

.footer{
    margin-top:20px;
    text-align:center;
}

.error{
    background:#7f1d1d;
    color:#fecaca;
    padding:12px;
    border-radius:10px;
    margin-bottom:16px;
}

.success{
    background:#14532d;
    color:#bbf7d0;
    padding:12px;
    border-radius:10px;
    margin-bottom:16px;
}
</style>
"""


def registration_closed_page():
    return f"""
    <html>
    <head>
        <title>Registration Closed</title>
        {AUTH_STYLES}
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>Registration closed</h1>
                <p>Business accounts are created by DebtCoach AI only.</p>
                <div class="footer">
                    <a href="/login">Go to login</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@router.get("/register", response_class=HTMLResponse)
def register_page(invite: str = ""):
    expected = os.getenv("ADMIN_INVITE_CODE")

    if not expected or invite != expected:
        return HTMLResponse(registration_closed_page(), status_code=403)

    return f"""
    <html>
    <head>
        <title>DebtCoach Register</title>
        {AUTH_STYLES}
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>DebtCoach AI</h1>
                <p>Create an approved business account</p>

                <form method="post" action="/register">
                    <input type="hidden" name="invite" value="{invite}">

                    <input name="business_name" placeholder="Business name" required>

                    <input 
                        name="email" 
                        type="email" 
                        placeholder="Email address" 
                        required
                    >

                    <input 
                        name="phone_e164" 
                        placeholder="Business WhatsApp number e.g. +27712345678"
                    >

                    <input 
                        name="password" 
                        type="password" 
                        placeholder="Password" 
                        required
                    >

                    <button>Create account</button>
                </form>

                <div class="footer">
                    <a href="/login">Already have an account? Login</a>
                </div>
            </div>
        </div>
    </body>
    </html>
    """


@router.post("/register")
def register(
    business_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    invite: str = Form(...),
    phone_e164: str = Form(""),
    db: Session = Depends(get_db),
):
    expected = os.getenv("ADMIN_INVITE_CODE")

    if not expected or invite != expected:
        return HTMLResponse("Registration closed.", status_code=403)

    email_clean = email.lower().strip()
    phone_clean = normalize_phone(phone_e164) if phone_e164 else None

    if phone_e164 and not phone_clean:
        return HTMLResponse("Invalid WhatsApp number. Use +27712345678.", status_code=400)

    existing_email = db.query(User).filter(User.email == email_clean).first()

    if existing_email:
        return HTMLResponse("Email already exists. <a href='/login'>Login</a>", status_code=400)

    if phone_clean:
        existing_phone = db.query(User).filter(User.phone_e164 == phone_clean).first()

        if existing_phone:
            return HTMLResponse("WhatsApp number already linked to another account.", status_code=400)

    user = User(
        business_name=business_name.strip(),
        email=email_clean,
        phone_e164=phone_clean,
        password_hash=hash_password(password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True)
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page(error: str = ""):
    error_html = ""

    if error:
        error_html = "<div class='error'>Invalid email or password.</div>"

    return f"""
    <html>
    <head>
        <title>DebtCoach Login</title>
        {AUTH_STYLES}
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>Welcome back</h1>
                <p>Login to your DebtCoach dashboard</p>

                {error_html}

                <form method="post" action="/login">
                    <input 
                        name="email" 
                        type="email" 
                        placeholder="Email address" 
                        required
                    >

                    <input 
                        name="password" 
                        type="password" 
                        placeholder="Password" 
                        required
                    >

                    <button>Login</button>
                </form>
            </div>
        </div>
    </body>
    </html>
    """


@router.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        return RedirectResponse("/login?error=1", status_code=303)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("user_id")
    return response