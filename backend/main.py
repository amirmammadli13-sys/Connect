import datetime
import hashlib
import os
import secrets
from typing import List, Optional

import bcrypt
import requests
from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session

from database import (
    Comment,
    Like,
    Post,
    SessionLocal,
    SessionToken,
    User,
    followers,
    init_db,
)

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://localhost:8001")
FEED_SIZE = 50

# Wie lange ein Token gilt, bevor man sich neu anmelden muss
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "30"))

# Cookie nur über HTTPS verschicken. Lokal läuft alles über http, deshalb aus.
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "0") == "1"
COOKIE_NAME = "connect_session"

# Das Frontend läuft im Betrieb hinter nginx auf derselben Domain. CORS brauchen
# wir nur für den Weg "index.html direkt im Browser öffnen" (Origin: null) und
# für lokale Dev-Server. Weitere Adressen lassen sich über CORS_ORIGINS ergänzen.
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost,http://127.0.0.1,http://localhost:8000,null"
    ).split(",")
    if origin.strip()
]

app = FastAPI(title="Connect API")

# allow_credentials muss an sein, damit der Browser das Session-Cookie mitschickt
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

init_db()


# ---------------------------------------------------------------- Schemas


class RegisterIn(BaseModel):
    username: str
    email: str
    password: str

    @field_validator("username")
    @classmethod
    def clean_username(cls, value: str) -> str:
        value = value.strip()
        if not 3 <= len(value) <= 30:
            raise ValueError("Username muss 3 bis 30 Zeichen lang sein")
        if not value.replace("_", "").replace(".", "").isalnum():
            raise ValueError("Username darf nur Buchstaben, Zahlen, _ und . enthalten")
        return value

    @field_validator("email")
    @classmethod
    def clean_email(cls, value: str) -> str:
        value = value.strip().lower()
        if "@" not in value or len(value) < 5:
            raise ValueError("Das sieht nicht nach einer E-Mail-Adresse aus")
        return value

    @field_validator("password")
    @classmethod
    def clean_password(cls, value: str) -> str:
        if len(value) < 6:
            raise ValueError("Passwort muss mindestens 6 Zeichen haben")
        return value


class LoginIn(BaseModel):
    username: str
    password: str
    # Der Client entscheidet, ob er ein Cookie will. Ohne Cookie gibt es den
    # Token in der Antwort und der Client legt ihn selbst ab.
    use_cookie: bool = True


class UserOut(BaseModel):
    id: int
    username: str
    email: str
    language: str

    model_config = ConfigDict(from_attributes=True)


class SessionOut(BaseModel):
    # Im Cookie-Modus fehlt der Token: er steckt dann nur im HttpOnly-Cookie
    token: Optional[str] = None
    expires_at: datetime.datetime
    user: UserOut


class PostIn(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Beitrag ist leer")
        if len(value) > 1000:
            raise ValueError("Beitrag darf höchstens 1000 Zeichen haben")
        return value


class PostOut(BaseModel):
    id: int
    user_id: int
    content: str
    username: str
    created_at: datetime.datetime
    likes: int
    comments: int
    liked_by_me: bool


class LikeOut(BaseModel):
    post_id: int
    likes: int
    liked: bool


class CommentIn(BaseModel):
    content: str

    @field_validator("content")
    @classmethod
    def clean_content(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Kommentar ist leer")
        if len(value) > 500:
            raise ValueError("Kommentar darf höchstens 500 Zeichen haben")
        return value


class CommentOut(BaseModel):
    id: int
    post_id: int
    user_id: int
    username: str
    content: str
    created_at: datetime.datetime


class FollowOut(BaseModel):
    username: str
    followers: int
    following: bool


class ProfileOut(BaseModel):
    id: int
    username: str
    joined: datetime.datetime
    posts_count: int
    followers: int
    following: int
    is_following: bool
    is_me: bool
    posts: List[PostOut]


# ---------------------------------------------------------------- Helpers


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Kaputter/leerer Hash in der Datenbank, dann ist es eben nicht das Passwort
        return False


def get_user_or_404(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")
    return user


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_DAYS * 24 * 60 * 60,
        path="/",
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )


def open_session(db: Session, user: User) -> tuple:
    """Legt eine neue Session an und räumt abgelaufene gleich mit weg.

    Gibt die Session und den Token im Klartext zurück - der wird nur einmal
    ausgegeben, in der Datenbank liegt ausschließlich der Hash.
    """
    now = datetime.datetime.now()
    db.query(SessionToken).filter(SessionToken.expires_at < now).delete()

    token = secrets.token_urlsafe(32)
    session = SessionToken(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=now + datetime.timedelta(days=SESSION_DAYS),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, token


def read_token(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def find_session(
    db: Session, token: Optional[str]
) -> Optional[SessionToken]:
    if not token:
        return None

    session = (
        db.query(SessionToken)
        .filter(SessionToken.token_hash == hash_token(token))
        .first()
    )
    if session and session.expires_at < datetime.datetime.now():
        db.delete(session)
        db.commit()
        return None
    return session


def resolve_session(
    db: Session, request: Request, authorization: Optional[str]
) -> tuple:
    """Sucht die Session erst im Authorization-Header, dann im Cookie.

    Zurück kommt die Session und woher sie stammt - das Cookie braucht wegen
    der automatischen Mitschickerei einen Extra-Schutz gegen CSRF.
    """
    token = read_token(authorization)
    if token:
        return find_session(db, token), "header"
    return find_session(db, request.cookies.get(COOKIE_NAME)), "cookie"


def check_cookie_request(request: Request) -> None:
    """Anfragen mit Cookie müssen den eigenen Header setzen.

    Ein fremdes Formular kann keinen Custom-Header schicken, ohne dass der
    Browser vorher einen Preflight macht - der scheitert an CORS.
    """
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return
    if request.headers.get("X-Connect") != "1":
        raise HTTPException(
            status_code=403,
            detail="Anfrage ohne X-Connect-Header abgelehnt",
        )


def get_current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    session, source = resolve_session(db, request, authorization)
    if not session:
        raise HTTPException(
            status_code=401,
            detail="Nicht angemeldet",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if source == "cookie":
        check_cookie_request(request)
    return session.user


def get_optional_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> Optional[User]:
    session, source = resolve_session(db, request, authorization)
    if not session:
        return None
    if source == "cookie":
        check_cookie_request(request)
    return session.user


def serialize_post(post: Post, db: Session, viewer: Optional[User] = None) -> dict:
    likes = db.query(Like).filter(Like.post_id == post.id).count()
    comments = db.query(Comment).filter(Comment.post_id == post.id).count()
    liked = False
    if viewer:
        liked = (
            db.query(Like)
            .filter(Like.post_id == post.id, Like.user_id == viewer.id)
            .first()
            is not None
        )
    return {
        "id": post.id,
        "user_id": post.user_id,
        "content": post.content,
        "username": post.author.username if post.author else "Unbekannt",
        "created_at": post.created_at,
        "likes": likes,
        "comments": comments,
        "liked_by_me": liked,
    }


def ranked_order(posts: List[Post], db: Session, viewer: Optional[User]) -> List[Post]:
    """Fragt den Ranking-Service nach der Reihenfolge.

    Ist der Service nicht erreichbar, bleibt es bei der chronologischen Liste -
    der Feed soll ja trotzdem laden.
    """
    if not viewer or len(posts) < 2:
        return posts

    now = datetime.datetime.now()
    followed_ids = [user.id for user in viewer.following]

    payload = {
        "user_id": viewer.id,
        "followed_ids": followed_ids,
        "posts": [
            {
                "post_id": post.id,
                "author_id": post.user_id,
                "likes": db.query(Like).filter(Like.post_id == post.id).count(),
                "comments": db.query(Comment).filter(Comment.post_id == post.id).count(),
                "age_hours": max((now - post.created_at).total_seconds() / 3600.0, 0.0),
            }
            for post in posts
        ],
    }

    try:
        response = requests.post(f"{AI_SERVICE_URL}/rank", json=payload, timeout=1.5)
        response.raise_for_status()
        order = [item["post_id"] for item in response.json()["ordered"]]
    except (requests.RequestException, KeyError, ValueError):
        return posts

    by_id = {post.id: post for post in posts}
    ranked = [by_id[post_id] for post_id in order if post_id in by_id]
    # Nichts verlieren, falls der Service mal eine ID unterschlägt
    ranked += [post for post in posts if post.id not in order]
    return ranked


# ---------------------------------------------------------------- Auth


@app.get("/")
def read_root():
    return {"message": "Connect API online"}


@app.post("/register", response_model=UserOut, status_code=201)
def register(user: RegisterIn, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == user.username).first():
        raise HTTPException(status_code=409, detail="Username ist schon vergeben")
    if db.query(User).filter(User.email == user.email).first():
        raise HTTPException(status_code=409, detail="E-Mail ist schon registriert")

    new_user = User(
        username=user.username,
        email=user.email,
        hashed_password=hash_password(user.password),
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.post("/login", response_model=SessionOut)
def login(
    data: LoginIn,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == data.username.strip()).first()
    if not user or not check_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Username oder Passwort falsch")

    # Alte Session aus demselben Browser nicht weiterleben lassen
    old = find_session(db, request.cookies.get(COOKIE_NAME))
    if old and old.user_id == user.id:
        db.delete(old)
        db.commit()

    session, token = open_session(db, user)
    if data.use_cookie:
        set_session_cookie(response, token)
        # Kein Token im Body: sonst könnte JavaScript ihn auslesen und der
        # Vorteil von HttpOnly wäre weg.
        return {"expires_at": session.expires_at, "user": user}
    return {"token": token, "expires_at": session.expires_at, "user": user}


@app.post("/logout", status_code=204)
def logout(
    response: Response,
    request: Request,
    authorization: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
):
    token = read_token(authorization) or request.cookies.get(COOKIE_NAME)
    session = find_session(db, token)
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return None


@app.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------- Posts & Feed


@app.post("/posts", response_model=PostOut, status_code=201)
def create_post(
    data: PostIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    post = Post(user_id=user.id, content=data.content)
    db.add(post)
    db.commit()
    db.refresh(post)
    return serialize_post(post, db, viewer=user)


@app.get("/feed", response_model=List[PostOut])
def get_feed(
    limit: int = FEED_SIZE,
    viewer: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 100))
    posts = (
        db.query(Post).order_by(Post.created_at.desc()).limit(max(limit, 200)).all()
    )
    posts = ranked_order(posts, db, viewer)[:limit]
    return [serialize_post(post, db, viewer=viewer) for post in posts]


@app.post("/posts/{post_id}/like", response_model=LikeOut)
def toggle_like(
    post_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Beitrag nicht gefunden")

    existing = (
        db.query(Like).filter(Like.post_id == post_id, Like.user_id == user.id).first()
    )
    if existing:
        db.delete(existing)
        liked = False
    else:
        db.add(Like(post_id=post_id, user_id=user.id))
        liked = True
    db.commit()

    likes = db.query(Like).filter(Like.post_id == post_id).count()
    return {"post_id": post_id, "likes": likes, "liked": liked}


@app.get("/posts/{post_id}/comments", response_model=List[CommentOut])
def get_comments(post_id: int, db: Session = Depends(get_db)):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Beitrag nicht gefunden")

    comments = (
        db.query(Comment)
        .filter(Comment.post_id == post_id)
        .order_by(Comment.created_at.asc())
        .all()
    )
    return [
        {
            "id": comment.id,
            "post_id": comment.post_id,
            "user_id": comment.user_id,
            "username": _comment_author(db, comment.user_id),
            "content": comment.content,
            "created_at": comment.created_at,
        }
        for comment in comments
    ]


def _comment_author(db: Session, user_id: int) -> str:
    user = db.query(User).filter(User.id == user_id).first()
    return user.username if user else "Unbekannt"


@app.post("/posts/{post_id}/comments", response_model=CommentOut, status_code=201)
def add_comment(
    post_id: int,
    data: CommentIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(status_code=404, detail="Beitrag nicht gefunden")

    comment = Comment(post_id=post_id, user_id=user.id, content=data.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return {
        "id": comment.id,
        "post_id": comment.post_id,
        "user_id": comment.user_id,
        "username": user.username,
        "content": comment.content,
        "created_at": comment.created_at,
    }


# ---------------------------------------------------------------- Profile & Follow


@app.get("/users/{username}", response_model=ProfileOut)
def get_profile(
    username: str,
    viewer: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")

    is_following = False
    if viewer and viewer.id != user.id:
        is_following = (
            db.query(followers)
            .filter(
                followers.c.follower_id == viewer.id,
                followers.c.followed_id == user.id,
            )
            .first()
            is not None
        )

    posts = (
        db.query(Post)
        .filter(Post.user_id == user.id)
        .order_by(Post.created_at.desc())
        .all()
    )

    return {
        "id": user.id,
        "username": user.username,
        "joined": user.created_at,
        "posts_count": len(posts),
        "followers": len(user.followers),
        "following": len(user.following),
        "is_following": is_following,
        "is_me": bool(viewer and viewer.id == user.id),
        "posts": [serialize_post(post, db, viewer=viewer) for post in posts],
    }


@app.post("/users/{username}/follow", response_model=FollowOut)
def toggle_follow(
    username: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    target = db.query(User).filter(User.username == username).first()
    if not target:
        raise HTTPException(status_code=404, detail="Nutzer nicht gefunden")
    if user.id == target.id:
        raise HTTPException(status_code=400, detail="Du kannst dir nicht selbst folgen")

    if target in user.following:
        user.following.remove(target)
        following = False
    else:
        user.following.append(target)
        following = True
    db.commit()
    db.refresh(target)

    return {
        "username": target.username,
        "followers": len(target.followers),
        "following": following,
    }
