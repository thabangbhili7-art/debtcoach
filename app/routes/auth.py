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

    return db.query(User).filter(User.id == int(user_id)).first()


AUTH_STYLES = """
<style>
body{
    margin:0;
    padding:0;
    background:#08152f;
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
    background:#13203d;
    padding:40px;
    border-radius:20px;
    width:380px;
    box-shadow:0 0 25px rgba(0,0,0,0.3);
}

h1{
    margin-top:0;
    font-size:36px;
}

p{
    color:#9ca3af;
}

input{
    width:100%;
    padding:14px;
    margin-top:12px;
    border-radius:10px;
    border:none;
    background:#08152f;
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
    background:#4ade80;
    color:black;
    font-size:16px;
    font-weight:bold;
    cursor:pointer;
}

button:hover{
    opacity:0.9;
}

a{
    color:#60a5fa;
    text-decoration:none;
}

.footer{
    margin-top:20px;
    text-align:center;
}
</style>
"""


@router.get("/register", response_class=HTMLResponse)
def register_page():
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
                <p>Create your business account</p>

                <form method="post" action="/register">
                    <input name="business_name" placeholder="Business name" required>

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
    db: Session = Depends(get_db),
):
    existing = db.query(User).filter(User.email == email.lower()).first()

    if existing:
        return HTMLResponse(
            "<h2>Email already exists. <a href='/login'>Login</a></h2>",
            status_code=400
        )

    user = User(
        business_name=business_name.strip(),
        email=email.lower().strip(),
        password_hash=hash_password(password),
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True)
    return response


@router.get("/login", response_class=HTMLResponse)
def login_page():
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

                <div class="footer">
                    <a href="/register">Create an account</a>
                </div>
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
        return HTMLResponse(
            "<h2>Invalid login. <a href='/login'>Try again</a></h2>",
            status_code=401
        )

    response = RedirectResponse("/dashboard", status_code=303)
    response.set_cookie("user_id", str(user.id), httponly=True)
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie("user_id")
    return response