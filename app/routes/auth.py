from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from ..db import get_db
from ..models import User

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


@router.get("/register", response_class=HTMLResponse)
def register_page():
    return """
    <h1>Create account</h1>
    <form method="post" action="/register">
        <input name="business_name" placeholder="Business name" required><br><br>
        <input name="email" type="email" placeholder="Email" required><br><br>
        <input name="password" type="password" placeholder="Password" required><br><br>
        <button>Create account</button>
    </form>
    <p><a href="/login">Already have an account? Login</a></p>
    """


@router.post("/register")
def register(
    business_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email.lower().strip()).first()

    if existing:
        return HTMLResponse("Email already exists. <a href='/login'>Login</a>", status_code=400)

    user = User(
        business_name=business_name.strip(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True, samesite="lax")
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page():
    return """
    <h1>Login</h1>
    <form method="post" action="/login">
        <input name="email" type="email" placeholder="Email" required><br><br>
        <input name="password" type="password" placeholder="Password" required><br><br>
        <button>Login</button>
    </form>
    <p><a href="/register">Create account</a></p>
    """


@router.post("/login")
def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == email.lower().strip()).first()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        return HTMLResponse("Invalid login. <a href='/login'>Try again</a>", status_code=401)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True, samesite="lax")
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("user_id")
    return response