import os, secrets, hashlib, ipaddress, re, json, asyncio, html
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4
from urllib.parse import urlparse
from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, EmailStr, Field as PField, field_validator
from sqlmodel import SQLModel, Field, Session, create_engine, select
from sqlalchemy import text, UniqueConstraint, inspect
from sqlalchemy.exc import IntegrityError
import bcrypt

UTC = timezone.utc
MAX_BODY_BYTES = 1_048_576
SUSPICIOUS_INPUT = re.compile(r"(?:<script|javascript:|onerror\\s*=|union\\s+select|drop\\s+table|\\.\\./|169\\.254\\.169\\.254)", re.I)

def safe_public_url(value: str) -> str:
    value = value.strip()
    if not value: return value
    p = urlparse(value)
    if p.scheme not in {"https"}: raise ValueError("A URL deve usar HTTPS")
    if not p.hostname: raise ValueError("URL inválida")
    try:
        ip = ipaddress.ip_address(p.hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved: raise ValueError("Endereço não permitido")
    except ValueError as e:
        if str(e) == "Endereço não permitido": raise
    if p.username or p.password or len(value) > 500: raise ValueError("URL não permitida")
    return value

UTC = timezone.utc
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./kayepad.db")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[11:]
elif DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL[13:]
sqlite = DATABASE_URL.startswith("sqlite")
engine = create_engine(DATABASE_URL, echo=False, pool_pre_ping=True,
    # Supabase poolers can reuse prepared-statement names across backend connections.
    # Disable psycopg auto-prepare so startup reflection and pooled requests are safe.
    connect_args={"check_same_thread": False} if sqlite else {"prepare_threshold": None})
def hash_password(value: str) -> str:
    return bcrypt.hashpw(value.encode(), bcrypt.gensalt()).decode()
def verify_password(value: str, hashed: str) -> bool:
    try: return bcrypt.checkpw(value.encode(), hashed.encode())
    except (ValueError, TypeError): return False
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET and os.getenv("ENVIRONMENT", "development") == "production":
    raise RuntimeError("JWT_SECRET is required in production")
JWT_SECRET = JWT_SECRET or "development-only-change-me"
app = FastAPI(title="Kayepad API", version="2.0.0")
origins = [x.strip() for x in os.getenv("CORS_ORIGINS", "https://kayepad.neocities.org,http://localhost:3000").split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET","POST","PATCH","DELETE","OPTIONS"], allow_headers=["Authorization","Content-Type","X-Admin-Key"])

class User(SQLModel, table=True):
    __tablename__ = "kp_users"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=320)
    pseudonym: str = Field(index=True, unique=True, max_length=40)
    password_hash: str
    bio: str = Field(default="", max_length=1000); avatar_url: str = Field(default="", max_length=500)
    badge: str = Field(default="normal", max_length=20); theme: str = Field(default="noir", max_length=20); email_verified: bool = False; banned: bool = False
    kaye_enabled: bool = True; created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class SessionToken(SQLModel, table=True):
    __tablename__ = "kp_sessions"
    id: UUID = Field(default_factory=uuid4, primary_key=True); user_id: UUID = Field(index=True)
    token_hash: str = Field(index=True, unique=True); expires_at: datetime; revoked: bool = False
class Work(SQLModel, table=True):
    __tablename__ = "kp_works"
    id: UUID = Field(default_factory=uuid4, primary_key=True); user_id: UUID = Field(index=True)
    title: str = Field(max_length=140); excerpt: str = Field(default="", max_length=3000); cover_url: str = Field(default="", max_length=500)
    chapters: int = 0; reads: int = 0; published: bool = True; created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class Chapter(SQLModel, table=True):
    __tablename__ = "kp_chapters"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    work_id: UUID = Field(index=True, foreign_key="kp_works.id")
    position: int = Field(default=1, index=True, ge=1, le=10000)
    title: str = Field(default="", max_length=140)
    content: str = Field(max_length=100000)
    published: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    __table_args__ = (UniqueConstraint("work_id", "position", name="uq_kp_chapter_position"),)

class Vote(SQLModel, table=True):
    __tablename__ = "kp_votes"
    id: UUID = Field(default_factory=uuid4, primary_key=True); work_id: UUID = Field(index=True); user_id: UUID = Field(index=True)
    __table_args__ = (UniqueConstraint("work_id", "user_id", name="uq_kp_vote"),)
class Comment(SQLModel, table=True):
    __tablename__ = "kp_comments"
    id: UUID = Field(default_factory=uuid4, primary_key=True); work_id: UUID = Field(index=True); user_id: UUID
    body: str = Field(max_length=2000); hidden: bool = False; created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class Game(SQLModel, table=True):
    __tablename__ = "kp_games"
    id: UUID = Field(default_factory=uuid4, primary_key=True); kind: str = Field(max_length=30); prompt: str = Field(max_length=1000); answer: str = Field(max_length=1000); cover_url: str = ""; active: bool = True
class Follow(SQLModel, table=True):
    __tablename__ = "kp_follows"
    follower_id: UUID = Field(primary_key=True); followed_id: UUID = Field(primary_key=True); created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class Notification(SQLModel, table=True):
    __tablename__ = "kp_notifications"
    id: UUID = Field(default_factory=uuid4, primary_key=True); recipient_id: UUID = Field(index=True); actor_id: Optional[UUID] = None
    kind: str = Field(max_length=20); title: str = Field(max_length=160); body: str = Field(max_length=1000); url: str = Field(default="", max_length=500)
    read_at: Optional[datetime] = None; created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class AuditEvent(SQLModel, table=True):
    __tablename__ = "kp_audit_events"
    id: UUID = Field(default_factory=uuid4, primary_key=True)
    action: str = Field(max_length=80, index=True); target_id: Optional[UUID] = Field(default=None, index=True)
    actor: str = Field(default="admin", max_length=80); ip_hash: str = Field(default="", max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC), index=True)

class PushSubscription(SQLModel, table=True):
    __tablename__ = "kp_push_subscriptions"
    id: UUID = Field(default_factory=uuid4, primary_key=True); user_id: UUID = Field(index=True); endpoint: str = Field(max_length=2000); p256dh: str = Field(max_length=500); auth: str = Field(max_length=500); created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    __table_args__ = (UniqueConstraint("user_id", "endpoint", name="uq_kp_push_user_endpoint"),)

class WritingRoom(SQLModel, table=True):
    __tablename__ = "kp_writing_rooms"
    id: UUID = Field(default_factory=uuid4, primary_key=True); owner_id: UUID = Field(index=True)
    title: str = Field(max_length=120); status: str = Field(default="open", max_length=20)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC)); closed_at: Optional[datetime] = None
class RoomParticipant(SQLModel, table=True):
    __tablename__ = "kp_room_participants"
    room_id: UUID = Field(primary_key=True); user_id: UUID = Field(primary_key=True, index=True)
    role: str = Field(default="editor", max_length=20); accepted: bool = False
    joined_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
class RoomInvite(SQLModel, table=True):
    __tablename__ = "kp_room_invites"
    id: UUID = Field(default_factory=uuid4, primary_key=True); room_id: UUID = Field(index=True); inviter_id: UUID = Field(index=True); invitee_id: UUID = Field(index=True)
    status: str = Field(default="pending", max_length=20); created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    __table_args__ = (UniqueConstraint("room_id", "invitee_id", name="uq_kp_room_invite"),)

def reject_malicious(value: str) -> str:
    if SUSPICIOUS_INPUT.search(value): raise ValueError("Conteúdo não permitido")
    return value.strip()

class Signup(BaseModel):
    email: EmailStr; pseudonym: str = PField(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_\.\-]+$"); password: str = PField(min_length=10, max_length=128)
    @field_validator("password")
    @classmethod
    def password_policy(cls, v):
        if not any(c.islower() for c in v) or not any(c.isupper() for c in v) or not any(c.isdigit() for c in v): raise ValueError("Senha deve conter maiúscula, minúscula e número")
        return v
class Login(BaseModel): email: EmailStr; password: str
class CommentIn(BaseModel):
    body: str = PField(min_length=1, max_length=2000)
    _safe = field_validator("body")(reject_malicious)
class ChapterIn(BaseModel):
    title: str = PField(default="", max_length=140)
    content: str = PField(min_length=1, max_length=100000)
    position: Optional[int] = PField(default=None, ge=1, le=10000)
    _safe = field_validator("title", "content")(reject_malicious)

class WorkIn(BaseModel):
    title: str = PField(min_length=1, max_length=140); excerpt: str = PField(default="", max_length=3000)
    cover_url: str = PField(default="", max_length=500); chapters: int = PField(default=0, ge=0, le=10000)
    # Optional convenience for clients creating a work and its first chapter atomically.
    initial_chapter: Optional[str] = PField(default=None, min_length=1, max_length=100000)
    initial_chapter_content: Optional[str] = PField(default=None, min_length=1, max_length=100000)
    initial_chapter_title: str = PField(default="", max_length=140)
    _safe = field_validator("title", "excerpt", "initial_chapter", "initial_chapter_content", "initial_chapter_title")(lambda v: reject_malicious(v) if v is not None else v)
    @field_validator("cover_url")
    @classmethod
    def cover_policy(cls, v): return safe_public_url(v)
class WorkPatch(BaseModel):
    title: Optional[str] = PField(None, min_length=1, max_length=140)
    excerpt: Optional[str] = PField(None, max_length=3000)
    cover_url: Optional[str] = PField(None, max_length=500)
    published: Optional[bool] = None
    _safe = field_validator("title", "excerpt")(lambda v: reject_malicious(v) if v is not None else v)
    @field_validator("cover_url")
    @classmethod
    def patch_cover_policy(cls, v): return safe_public_url(v) if v is not None else v
class ChapterPatch(BaseModel):
    title: Optional[str] = PField(None, max_length=140)
    content: Optional[str] = PField(None, min_length=1, max_length=100000)
    position: Optional[int] = PField(None, ge=1, le=10000)
    published: Optional[bool] = None
    _safe = field_validator("title", "content")(lambda v: reject_malicious(v) if v is not None else v)
class ProfilePatch(BaseModel):
    pseudonym: Optional[str] = PField(None, min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_\.\-]+$")
    bio: Optional[str] = PField(None, max_length=1000); avatar_url: Optional[str] = PField(None, max_length=500); theme: Optional[str] = None; kaye_enabled: Optional[bool] = None
    _safe = field_validator("bio")(lambda v: reject_malicious(v) if v is not None else v)
    @field_validator("theme")
    @classmethod
    def theme_policy(cls, v):
        allowed={"noir","cafe","algodao","brasil","medium","wattpad","gold","neon","inverno","verao","outono","primavera","patria"}
        if v not in allowed: raise ValueError("Tema inválido")
        return v
    @field_validator("avatar_url")
    @classmethod
    def avatar_policy(cls, v): return safe_public_url(v) if v is not None else v
class BadgeIn(BaseModel): badge: str
class KayeIn(BaseModel):
    message: str = PField(min_length=1, max_length=1000)
    _safe = field_validator("message")(reject_malicious)

_requests = {}
def rate_limit(request: Request):
    key = (request.client.host if request.client else "unknown", request.url.path.split('/')[1])
    now = datetime.now(UTC).timestamp(); window = 60
    bucket = [t for t in _requests.get(key, []) if now-t < window]
    ceiling = 12 if request.url.path in {"/auth/login", "/auth/signup"} else int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
    if len(bucket) >= ceiling: raise HTTPException(429, "Muitas solicitações; tente novamente em instantes")
    bucket.append(now); _requests[key] = bucket
@app.middleware("http")
async def security_gate(request: Request, call_next):
    try:
        if request.headers.get("content-length") and int(request.headers["content-length"]) > MAX_BODY_BYTES: raise HTTPException(413, "Requisição muito grande")
        if SUSPICIOUS_INPUT.search(str(request.url.query)): raise HTTPException(400, "Requisição não permitida")
        if request.method in {"POST", "PATCH", "PUT", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and origin not in origins: raise HTTPException(403, "Origem não permitida")
        rate_limit(request)
        response = await call_next(request)
        response.headers.update({"X-Content-Type-Options":"nosniff","X-Frame-Options":"DENY","Referrer-Policy":"strict-origin-when-cross-origin","Content-Security-Policy":"default-src 'none'; frame-ancestors 'none'"})
        return response
    except HTTPException as e: return JSONResponse({"detail": e.detail}, status_code=e.status_code, headers={"X-Content-Type-Options":"nosniff"})

def public_user(u): return {"id":str(u.id),"pseudonym":u.pseudonym,"bio":u.bio,"avatar_url":u.avatar_url,"badge":u.badge,"theme":getattr(u,"theme","noir"),"kaye_enabled":u.kaye_enabled}
def notification_json(n): return {"id":str(n.id),"kind":n.kind,"title":n.title,"body":n.body,"url":n.url,"read":n.read_at is not None,"created_at":n.created_at}
def provision_official(s):
    official=s.exec(select(User).where(User.pseudonym=="KayepadOficial")).first()
    if not official:
        # No recoverable credential is stored or returned; this account is content-only.
        official=User(email="official@kayepad.invalid", pseudonym="KayepadOficial", bio="Perfil oficial da Kayepad: novidades da plataforma, histórias da casa e caminhos para ler e escrever.", password_hash=hash_password(secrets.token_urlsafe(48)), badge="official_gold", email_verified=True)
        s.add(official); s.flush()
    elif not official.bio:
        official.bio="Perfil oficial da Kayepad: novidades da plataforma, histórias da casa e caminhos para ler e escrever."
        s.add(official)
    return official
def issue(u):
    raw = secrets.token_urlsafe(48); h = hashlib.sha256(raw.encode()).hexdigest()
    with Session(engine) as s: s.add(SessionToken(user_id=u.id, token_hash=h, expires_at=datetime.now(UTC)+timedelta(days=30))); s.commit()
    return raw
def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401,"Autenticação necessária")
    h=hashlib.sha256(authorization[7:].encode()).hexdigest()
    with Session(engine) as s:
        st=s.exec(select(SessionToken).where(SessionToken.token_hash==h, SessionToken.revoked==False)).first()
        expiry = st.expires_at.replace(tzinfo=UTC) if st and st.expires_at.tzinfo is None else (st.expires_at if st else None)
        if not st or expiry < datetime.now(UTC): raise HTTPException(401,"Sessão inválida ou expirada")
        u=s.get(User,st.user_id)
        if not u or u.banned: raise HTTPException(403,"Conta banida")
        return u
def admin_key(x_admin_key: Optional[str]=Header(None)):
    key=os.getenv("ADMIN_API_KEY")
    if not key or not x_admin_key or not secrets.compare_digest(key,x_admin_key): raise HTTPException(403,"Acesso administrativo negado")

def audit(s, action: str, target_id=None, request: Request | None=None):
    # Store only a keyed digest of the address; raw IPs never enter the database or logs.
    raw = request.client.host if request and request.client else "unknown"
    digest = hashlib.sha256((os.getenv("IP_HASH_SALT", "kayepad-privacy") + raw).encode()).hexdigest()
    s.add(AuditEvent(action=action, target_id=target_id, ip_hash=digest))

def clean_output(value):
    # API responses are rendered by multiple clients; escape markup at the boundary
    # so stored plain text can never become HTML in an unsafe consumer.
    return html.escape(str(value), quote=True)

def chapter_json(c):
    return {"id": str(c.id), "work_id": str(c.work_id), "position": c.position,
            "title": c.title, "content": c.content,
            "published": c.published, "created_at": c.created_at}

def work_json(s,w):
    a=s.get(User,w.user_id); votes=len(s.exec(select(Vote).where(Vote.work_id==w.id)).all())
    return {"id":str(w.id),"title":w.title,"excerpt":w.excerpt,"cover_url":w.cover_url,"chapters":w.chapters,"reads":w.reads,"votes":votes,"author":a.pseudonym if a else "", "badge":a.badge if a else "normal", "published":w.published}
@app.on_event("startup")
def startup():
    # Keep startup compatible with both a fresh SQLite database and an existing
    # Supabase/PostgreSQL schema.  create_all is intentionally additive; the
    # inspector avoids querying information_schema directly (which can resolve
    # the wrong schema with pooled connections or restricted DB roles).
    SQLModel.metadata.create_all(engine)
    inspector = inspect(engine)
    user_columns = {column["name"] for column in inspector.get_columns("kp_users")}
    if "theme" not in user_columns:
        with engine.begin() as conn:
            if sqlite:
                conn.execute(text("ALTER TABLE kp_users ADD COLUMN theme VARCHAR(20) NOT NULL DEFAULT 'noir'"))
            else:
                conn.execute(text("ALTER TABLE kp_users ADD COLUMN IF NOT EXISTS theme VARCHAR(20) NOT NULL DEFAULT 'noir'"))
    with Session(engine) as s:
        provision_official(s); s.commit()
@app.get("/health")
def health(): return {"status":"ok","service":"kayepad-api","time":datetime.now(UTC)}
@app.get("/ready")
def ready():
    try:
        with Session(engine) as s: s.exec(text("SELECT 1"))
        return {"status":"ready","database":"ok"}
    except Exception: raise HTTPException(503,"Banco de dados indisponível")
@app.post("/auth/signup")
def signup(data: Signup):
    normalized_email = str(data.email).lower()
    with Session(engine) as s:
        if data.pseudonym.casefold()=="kayepadoficial" or s.exec(select(User).where((User.email==normalized_email) | (User.pseudonym==data.pseudonym))).first(): raise HTTPException(409,"E-mail ou pseudônimo já cadastrado")
        # Signup, official follow and welcome message are one database transaction.
        official=provision_official(s)
        u=User(email=normalized_email,pseudonym=data.pseudonym,password_hash=hash_password(data.password)); s.add(u); s.flush()
        s.add(Follow(follower_id=u.id, followed_id=official.id))
        s.add(Notification(recipient_id=u.id, actor_id=official.id, kind="welcome", title="Bem-vindo à Kayepad", body="Que bom ter você aqui. Comece seguindo histórias e deixando sua própria voz encontrar caminhos.", url="/poficial"))
        s.commit(); s.refresh(u); return {"user":public_user(u),"token":issue(u)}
@app.post("/auth/login")
def login(data: Login):
    with Session(engine) as s: u=s.exec(select(User).where(User.email==str(data.email).lower())).first()
    if not u or not verify_password(data.password,u.password_hash): raise HTTPException(401,"Credenciais inválidas")
    if u.banned: raise HTTPException(403,"Conta banida")
    return {"user":public_user(u),"token":issue(u)}
class DeleteMeIn(BaseModel):
    confirmation: str = PField(min_length=6, max_length=20)

@app.delete("/me")
def delete_me(data: DeleteMeIn, request: Request, u=Depends(current_user)):
    if data.confirmation != "DELETE":
        raise HTTPException(400, "Confirmação inválida; envie confirmation=DELETE")
    with Session(engine) as s:
        db=s.get(User,u.id)
        if not db: raise HTTPException(404, "Conta não encontrada")
        # Explicit deletion keeps this safe on older SQLite installations without FK cascades.
        work_ids=[w.id for w in s.exec(select(Work).where(Work.user_id==db.id)).all()]
        owned_room_ids=[r.id for r in s.exec(select(WritingRoom).where(WritingRoom.owner_id==db.id)).all()]
        for rid in owned_room_ids:
            for model in (RoomParticipant, RoomInvite):
                for row in s.exec(select(model).where(model.room_id==rid)).all(): s.delete(row)
            room=s.get(WritingRoom,rid)
            if room: s.delete(room)
        for model, predicate in [(Vote, Vote.user_id==db.id), (Comment, Comment.user_id==db.id),
            (Follow, (Follow.follower_id==db.id) | (Follow.followed_id==db.id)),
            (Notification, (Notification.recipient_id==db.id) | (Notification.actor_id==db.id)),
            (PushSubscription, PushSubscription.user_id==db.id), (RoomParticipant, RoomParticipant.user_id==db.id),
            (RoomInvite, (RoomInvite.inviter_id==db.id) | (RoomInvite.invitee_id==db.id))]:
            for row in s.exec(select(model).where(predicate)).all(): s.delete(row)
        for wid in work_ids:
            for model in (Vote, Comment, Chapter):
                for row in s.exec(select(model).where(model.work_id==wid)).all(): s.delete(row)
            work=s.get(Work,wid)
            if work: s.delete(work)
        for st in s.exec(select(SessionToken).where(SessionToken.user_id==db.id)).all(): s.delete(st)
        audit(s, "user.delete", db.id, request)
        s.delete(db); s.commit()
    return {"ok": True, "deleted": True}

@app.post("/me/sessions/revoke")
def revoke_sessions(u=Depends(current_user)):
    with Session(engine) as s:
        sessions=s.exec(select(SessionToken).where(SessionToken.user_id==u.id, SessionToken.revoked==False)).all()
        for st in sessions: st.revoked=True; s.add(st)
        s.commit()
    return {"ok": True, "revoked": len(sessions)}

@app.delete("/auth/logout")
def logout(authorization: Optional[str]=Header(None), u=Depends(current_user)):
    if authorization:
        with Session(engine) as s:
            st=s.exec(select(SessionToken).where(SessionToken.token_hash==hashlib.sha256(authorization[7:].encode()).hexdigest())).first()
            if st: st.revoked=True; s.add(st); s.commit()
    return {"ok":True}
def refresh_verified(s, u):
    age = datetime.now(UTC) - (u.created_at.replace(tzinfo=UTC) if u.created_at.tzinfo is None else u.created_at)
    total = len(s.exec(select(Work).where(Work.user_id==u.id, Work.published)).all())
    if u.email_verified and age > timedelta(days=30) and total >= 3 and u.badge == "normal":
        u.badge = "verified"; s.add(u); s.commit(); s.refresh(u)
@app.get("/me")
def me(u=Depends(current_user)):
    with Session(engine) as s:
        db=s.get(User,u.id); refresh_verified(s,db); return public_user(db)
@app.patch("/me")
def patch_me(data: ProfilePatch,u=Depends(current_user)):
    with Session(engine) as s:
        db=s.get(User,u.id)
        updates=data.model_dump(exclude_none=True)
        if "pseudonym" in updates and updates["pseudonym"] != db.pseudonym:
            if s.exec(select(User).where(User.pseudonym==updates["pseudonym"], User.id!=db.id)).first(): raise HTTPException(409,"Pseudônimo já cadastrado")
        for k,v in updates.items(): setattr(db,k,v)
        s.add(db); s.commit(); s.refresh(db); return public_user(db)
def public_profile_json(s, user, viewer_id=None):
    published=s.exec(select(Work).where(Work.user_id==user.id, Work.published==True).order_by(Work.created_at.desc())).all()
    followers_count=len(s.exec(select(Follow).where(Follow.followed_id==user.id)).all())
    following_count=len(s.exec(select(Follow).where(Follow.follower_id==user.id)).all())
    return {"id":str(user.id),"pseudonym":user.pseudonym,"bio":user.bio,"badge":user.badge,"avatar_url":user.avatar_url,
            "followers":followers_count,"following":following_count,
            "is_following":bool(viewer_id and s.exec(select(Follow).where(Follow.follower_id==viewer_id,Follow.followed_id==user.id)).first()),
            "works":[work_json(s,w) for w in published]}

@app.get("/public/profiles/{pseudonym}")
def public_profile(pseudonym: str, authorization: Optional[str] = Header(None)):
    """Public profile projection, including published works and follow state when signed in."""
    with Session(engine) as s:
        user=s.exec(select(User).where(User.pseudonym.ilike(pseudonym), User.banned==False)).first()
        if not user: raise HTTPException(404, "Perfil não encontrado")
        viewer_id=None
        if authorization and authorization.startswith("Bearer "):
            st=s.exec(select(SessionToken).where(SessionToken.token_hash==hashlib.sha256(authorization[7:].encode()).hexdigest(),SessionToken.revoked==False)).first()
            if st: viewer_id=st.user_id
        return public_profile_json(s,user,viewer_id)

@app.get("/public/users/search")
def public_search_users(q: str = Query("", min_length=2, max_length=40), limit: int = Query(20, ge=1, le=50)):
    """Search visible authors without requiring a session; never returns email or private fields."""
    term=q.strip()
    if not term: return []
    with Session(engine) as s:
        rows=s.exec(select(User).where(User.pseudonym.ilike(f"%{term}%"), User.banned==False).order_by(User.pseudonym).limit(limit)).all()
        return [{"id":str(x.id),"pseudonym":x.pseudonym,"bio":x.bio,"avatar_url":x.avatar_url,"badge":x.badge,
                 "works_count":len(s.exec(select(Work).where(Work.user_id==x.id,Work.published==True)).all())} for x in rows]

@app.get("/works")
def works(limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0)):
    with Session(engine) as s: return [work_json(s,w) for w in s.exec(select(Work).where(Work.published).order_by(Work.created_at.desc()).offset(offset).limit(limit)).all()]
@app.get("/me/works")
def my_works(u=Depends(current_user)):
    with Session(engine) as s:
        return [work_json(s,w) for w in s.exec(select(Work).where(Work.user_id==u.id).order_by(Work.created_at.desc())).all()]

@app.get("/works/{work_id}")
def work_detail(work_id: UUID, authorization: Optional[str] = Header(None)):
    with Session(engine) as s:
        w=s.get(Work, work_id)
        if not w: raise HTTPException(404, "Obra não encontrada")
        # Published works are public. An owner may inspect an unpublished draft with a valid session.
        if not w.published:
            owner = None
            if authorization and authorization.startswith("Bearer "):
                token_hash=hashlib.sha256(authorization[7:].encode()).hexdigest()
                st=s.exec(select(SessionToken).where(SessionToken.token_hash==token_hash, SessionToken.revoked==False)).first()
                candidate=s.get(User, st.user_id) if st else None
                if st and candidate and not candidate.banned and (st.expires_at.replace(tzinfo=UTC) if st.expires_at.tzinfo is None else st.expires_at) >= datetime.now(UTC): owner=candidate
            if not owner or owner.id != w.user_id: raise HTTPException(404, "Obra não encontrada")
        return work_json(s,w)

@app.get("/works/{work_id}/chapters")
def work_chapters(work_id: UUID, authorization: Optional[str] = Header(None)):
    with Session(engine) as s:
        w=s.get(Work, work_id)
        if not w: raise HTTPException(404, "Obra não encontrada")
        owner = False
        if not w.published:
            token_hash=hashlib.sha256(authorization[7:].encode()).hexdigest() if authorization and authorization.startswith("Bearer ") else ""
            st=s.exec(select(SessionToken).where(SessionToken.token_hash==token_hash, SessionToken.revoked==False)).first()
            expiry = (st.expires_at.replace(tzinfo=UTC) if st and st.expires_at.tzinfo is None else (st.expires_at if st else None))
            owner = bool(st and expiry and expiry >= datetime.now(UTC) and st.user_id == w.user_id and s.get(User, st.user_id) and not s.get(User, st.user_id).banned)
            if not owner: raise HTTPException(404, "Obra não encontrada")
        query=select(Chapter).where(Chapter.work_id==work_id)
        if not owner: query=query.where(Chapter.published==True)
        return [chapter_json(c) for c in s.exec(query.order_by(Chapter.position)).all()]

@app.post("/works")
def create_work(data: WorkIn, u=Depends(current_user)):
    with Session(engine) as s:
        initial_content=data.initial_chapter_content or data.initial_chapter
        initial_count=1 if initial_content else 0
        w=Work(user_id=u.id, title=data.title.strip(), excerpt=data.excerpt.strip(), cover_url=data.cover_url.strip(), chapters=initial_count)
        s.add(w); s.flush()
        if initial_content:
            s.add(Chapter(work_id=w.id, position=1, title=data.initial_chapter_title.strip(), content=initial_content.strip()))
        followers_ids=[f.follower_id for f in s.exec(select(Follow).where(Follow.followed_id==u.id)).all()]
        for recipient in followers_ids:
            s.add(Notification(recipient_id=recipient,actor_id=u.id,kind="post",title=f"{u.pseudonym} publicou uma obra",body=data.title.strip(),url=f"/works/{w.id}"))
        s.commit(); s.refresh(w); return work_json(s,w)

@app.post("/works/{work_id}/chapters")
def add_chapter(work_id: UUID, data: ChapterIn, u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work, work_id)
        if not w: raise HTTPException(404, "Obra não encontrada")
        if w.user_id != u.id: raise HTTPException(403, "Somente o proprietário pode adicionar capítulos")
        position=data.position
        if position is None:
            last=s.exec(select(Chapter).where(Chapter.work_id==work_id).order_by(Chapter.position.desc())).first()
            position=(last.position + 1) if last else 1
        if s.exec(select(Chapter).where(Chapter.work_id==work_id, Chapter.position==position)).first(): raise HTTPException(409, "Posição de capítulo já existe")
        c=Chapter(work_id=work_id, position=position, title=data.title.strip(), content=data.content.strip())
        s.add(c); s.flush(); w.chapters=len(s.exec(select(Chapter).where(Chapter.work_id==work_id)).all()); s.add(w); s.commit(); s.refresh(c)
        return chapter_json(c)
@app.patch("/works/{work_id}")
def update_work(work_id: UUID, data: WorkPatch, u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work, work_id)
        if not w: raise HTTPException(404,"Obra não encontrada")
        if w.user_id != u.id: raise HTTPException(403,"Somente o proprietário pode editar a obra")
        for k,v in data.model_dump(exclude_none=True).items(): setattr(w,k,v)
        s.add(w); s.commit(); s.refresh(w); return work_json(s,w)

@app.patch("/works/{work_id}/chapters/{chapter_id}")
def update_chapter(work_id: UUID, chapter_id: UUID, data: ChapterPatch, u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work, work_id); c=s.get(Chapter, chapter_id)
        if not w or not c or c.work_id != work_id: raise HTTPException(404,"Capítulo não encontrado")
        if w.user_id != u.id: raise HTTPException(403,"Somente o proprietário pode editar o capítulo")
        updates=data.model_dump(exclude_none=True)
        if "position" in updates and s.exec(select(Chapter).where(Chapter.work_id==work_id,Chapter.position==updates["position"],Chapter.id!=chapter_id)).first(): raise HTTPException(409,"Posição de capítulo já existe")
        for k,v in updates.items(): setattr(c,k,v)
        s.add(c); s.commit(); s.refresh(c); return chapter_json(c)
@app.delete("/works/{work_id}/chapters/{chapter_id}")
def delete_chapter(work_id: UUID, chapter_id: UUID, u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work, work_id); c=s.get(Chapter, chapter_id)
        if not w or not c or c.work_id != work_id: raise HTTPException(404,"Capítulo não encontrado")
        if w.user_id != u.id: raise HTTPException(403,"Somente o proprietário pode excluir o capítulo")
        s.delete(c); s.flush(); remaining=s.exec(select(Chapter).where(Chapter.work_id==work_id)).all(); w.chapters=len(remaining); s.add(w); s.commit(); return {"ok":True,"deleted":True}
@app.delete("/works/{work_id}")
def delete_work(work_id: UUID, request: Request, u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work, work_id)
        if not w: raise HTTPException(404, "Obra não encontrada")
        if w.user_id != u.id: raise HTTPException(403, "Somente o proprietário pode excluir a obra")
        for model in (Vote, Comment, Chapter):
            for row in s.exec(select(model).where(model.work_id==work_id)).all(): s.delete(row)
        s.delete(w); audit(s, "work.delete", work_id, request); s.commit()
    return {"ok": True, "deleted": True}
@app.post("/works/{work_id}/read")
def read(work_id:UUID):
    with Session(engine) as s:
        w=s.get(Work,work_id)
        if not w or not w.published: raise HTTPException(404,"Obra não encontrada")
        w.reads+=1; s.add(w); s.commit(); return {"reads":w.reads}
@app.post("/works/{work_id}/vote")
def vote(work_id:UUID,u=Depends(current_user)):
    with Session(engine) as s:
        w=s.get(Work,work_id)
        if not w or not w.published: raise HTTPException(404,"Obra não encontrada")
        if s.exec(select(Vote).where(Vote.work_id==work_id,Vote.user_id==u.id)).first(): raise HTTPException(409,"Você já votou nesta obra")
        s.add(Vote(work_id=work_id,user_id=u.id)); s.commit(); return {"votes":len(s.exec(select(Vote).where(Vote.work_id==work_id)).all())}
@app.get("/works/{work_id}/comments")
def comments(work_id:UUID):
    with Session(engine) as s: return [{"id":str(c.id),"body":c.body,"created_at":c.created_at,"user_id":str(c.user_id)} for c in s.exec(select(Comment).where(Comment.work_id==work_id,Comment.hidden==False).order_by(Comment.created_at.desc())).all()]
@app.post("/works/{work_id}/comments")
def add_comment(work_id:UUID,data:CommentIn,u=Depends(current_user)):
    with Session(engine) as s:
        work=s.get(Work,work_id)
        if not work or not work.published: raise HTTPException(404,"Obra não encontrada")
        c=Comment(work_id=work_id,user_id=u.id,body=data.body.strip()); s.add(c); s.commit(); s.refresh(c); return {"id":str(c.id),"body":c.body,"created_at":c.created_at}
@app.get("/users/{user_id}/followers")
def followers(user_id:UUID, limit:int=Query(50,ge=1,le=100)):
    with Session(engine) as s:
        if not s.get(User,user_id): raise HTTPException(404,"Usuário não encontrado")
        return [public_user(u) for u in [s.get(User,f.follower_id) for f in s.exec(select(Follow).where(Follow.followed_id==user_id).order_by(Follow.created_at.desc()).limit(limit)).all()] if u]
@app.get("/users/{user_id}/following")
def following(user_id:UUID, limit:int=Query(50,ge=1,le=100)):
    with Session(engine) as s:
        if not s.get(User,user_id): raise HTTPException(404,"Usuário não encontrado")
        return [public_user(u) for u in [s.get(User,f.followed_id) for f in s.exec(select(Follow).where(Follow.follower_id==user_id).order_by(Follow.created_at.desc()).limit(limit)).all()] if u]
@app.post("/users/{user_id}/follow")
def follow(user_id:UUID, u=Depends(current_user)):
    if user_id==u.id: raise HTTPException(400,"Você não pode seguir a si mesmo")
    with Session(engine) as s:
        target=s.get(User,user_id)
        if not target or target.banned: raise HTTPException(404,"Usuário não encontrado")
        if s.exec(select(Follow).where(Follow.follower_id==u.id,Follow.followed_id==user_id)).first(): return {"following":True}
        try:
            s.add(Follow(follower_id=u.id,followed_id=user_id)); s.add(Notification(recipient_id=user_id,actor_id=u.id,kind="follow",title="Novo seguidor",body=f"{u.pseudonym} começou a seguir você.",url=f"/perfil/{u.id}")); s.commit()
        except IntegrityError: s.rollback()
        return {"following":True}
@app.delete("/users/{user_id}/follow")
def unfollow(user_id:UUID, u=Depends(current_user)):
    with Session(engine) as s:
        f=s.exec(select(Follow).where(Follow.follower_id==u.id,Follow.followed_id==user_id)).first()
        if f: s.delete(f); s.commit()
        return {"following":False}
@app.get("/me/following")
def my_following(u=Depends(current_user)): return following(u.id,50)
@app.get("/notifications")
def notifications(limit:int=Query(50,ge=1,le=100), u=Depends(current_user)):
    with Session(engine) as s: return [notification_json(n) for n in s.exec(select(Notification).where(Notification.recipient_id==u.id).order_by(Notification.created_at.desc()).limit(limit)).all()]
@app.post("/notifications/{notification_id}/read")
def mark_notification_read(notification_id:UUID,u=Depends(current_user)):
    with Session(engine) as s:
        n=s.get(Notification,notification_id)
        if not n or n.recipient_id!=u.id: raise HTTPException(404,"Notificação não encontrada")
        n.read_at=datetime.now(UTC); s.add(n); s.commit(); return notification_json(n)
class PushIn(BaseModel): endpoint:str=PField(min_length=10,max_length=2000); p256dh:str=PField(min_length=10,max_length=500); auth:str=PField(min_length=5,max_length=500)
@app.post("/push/subscriptions")
def save_push(data:PushIn,u=Depends(current_user)):
    with Session(engine) as s:
        p=s.exec(select(PushSubscription).where(PushSubscription.user_id==u.id,PushSubscription.endpoint==data.endpoint)).first()
        if p: p.p256dh=data.p256dh; p.auth=data.auth
        else: p=PushSubscription(user_id=u.id,**data.model_dump()); s.add(p)
        s.commit(); return {"ok":True,"push":"stored"}
@app.delete("/push/subscriptions")
def delete_push(data:PushIn,u=Depends(current_user)):
    with Session(engine) as s:
        p=s.exec(select(PushSubscription).where(PushSubscription.user_id==u.id,PushSubscription.endpoint==data.endpoint)).first()
        if p: s.delete(p); s.commit()
        return {"ok":True}

def dispatch_push(user_id: UUID, payload: dict) -> dict:
    """Best-effort provider worker; subscriptions are pruned on permanent endpoint failure."""
    public=os.getenv("VAPID_PUBLIC_KEY"); private=os.getenv("VAPID_PRIVATE_KEY"); subject=os.getenv("VAPID_SUBJECT", "mailto:admin@kayepad.invalid")
    if not public or not private: return {"configured": False, "sent": 0, "failed": 0}
    try:
        from pywebpush import webpush, WebPushException
    except ImportError: return {"configured": False, "sent": 0, "failed": 0, "reason": "pywebpush_not_installed"}
    sent=failed=0
    with Session(engine) as s:
        subs=s.exec(select(PushSubscription).where(PushSubscription.user_id==user_id)).all()
        for sub in subs:
            try:
                webpush(subscription_info={"endpoint":sub.endpoint,"keys":{"p256dh":sub.p256dh,"auth":sub.auth}}, data=json.dumps(payload), vapid_private_key=private, vapid_claims={"sub":subject})
                sent += 1
            except WebPushException as exc:
                failed += 1
                if getattr(exc, "response", None) is not None and getattr(exc.response, "status_code", 0) in {404,410}: s.delete(sub)
        s.commit()
    return {"configured": True, "sent": sent, "failed": failed}
@app.get("/push/status")
def push_status(u=Depends(current_user)):
    with Session(engine) as s: count=len(s.exec(select(PushSubscription).where(PushSubscription.user_id==u.id)).all())
    return {"configured": bool(os.getenv("VAPID_PUBLIC_KEY") and os.getenv("VAPID_PRIVATE_KEY")), "subscriptions": count, "vapid_public_key": os.getenv("VAPID_PUBLIC_KEY", "")}
@app.post("/push/test")
def push_test(u=Depends(current_user)):
    return dispatch_push(u.id, {"title":"Kayepad", "body":"Teste de notificações push", "url":"/"})
@app.get("/reels")
def reels(limit:int=Query(30,ge=1,le=100)): return works(limit,0)
@app.get("/games")
def games(kind:Optional[str]=None):
    with Session(engine) as s: return s.exec(select(Game).where(Game.active, Game.kind==kind if kind else True)).all()
@app.post("/kaye")
def kaye(data:KayeIn,u=Depends(current_user)):
    if not u.kaye_enabled: raise HTTPException(403,"Kaye está desativada nas suas configurações")
    msg=data.message.lower(); replies=[("perfil","Você pode atualizar bio, avatar e a preferência da Kaye em /me."),("config","Abra suas configurações para controlar a Kaye e seu perfil."),("post","Para publicar uma obra, use o endpoint de obras autenticado."),("vot","Você pode votar uma vez em cada obra."),("coment","Comentários devem respeitar a comunidade e têm limite de 2.000 caracteres.")]
    answer=next((r for k,r in replies if k in msg),"Posso ajudar com perfil, configurações, posts, comentários e interações. Diga o que você precisa.")
    return {"answer":answer}

class RoomIn(BaseModel):
    title: str = PField(min_length=1, max_length=120)
    _safe = field_validator("title")(reject_malicious)
class InviteIn(BaseModel): invitee_id: UUID
class PermissionIn(BaseModel): role: str
_room_activity = {}
_room_connections: dict[str, set[WebSocket]] = {}

def room_member(s, room_id, user_id, accepted=True):
    return s.exec(select(RoomParticipant).where(RoomParticipant.room_id==room_id, RoomParticipant.user_id==user_id, RoomParticipant.accepted==accepted)).first()
def room_json(s, room):
    parts=s.exec(select(RoomParticipant).where(RoomParticipant.room_id==room.id, RoomParticipant.accepted==True)).all()
    return {"id":str(room.id),"title":room.title,"owner_id":str(room.owner_id),"status":room.status,"participants":[{"user_id":str(p.user_id),"pseudonym":(s.get(User,p.user_id).pseudonym if s.get(User,p.user_id) else "Pessoa Kayepad"),"role":p.role} for p in parts],"created_at":room.created_at}
@app.post("/rooms")
def create_room(data: RoomIn, u=Depends(current_user)):
    with Session(engine) as s:
        room=WritingRoom(owner_id=u.id,title=data.title.strip()); s.add(room); s.flush(); s.add(RoomParticipant(room_id=room.id,user_id=u.id,role="owner",accepted=True)); s.commit(); s.refresh(room); return room_json(s,room)
@app.post("/rooms/{room_id}/invites")
def invite_room(room_id: UUID, data: InviteIn, u=Depends(current_user)):
    with Session(engine) as s:
        room=s.get(WritingRoom,room_id)
        if not room or room.status!="open": raise HTTPException(404,"Sala não encontrada ou fechada")
        if room.owner_id != u.id: raise HTTPException(403,"Somente o proprietário pode convidar")
        max_participants=int(os.getenv("ROOM_MAX_PARTICIPANTS", "8"))
        participant_count=len(s.exec(select(RoomParticipant).where(RoomParticipant.room_id==room_id,RoomParticipant.accepted==True)).all())
        if participant_count >= max_participants: raise HTTPException(409,"Limite de participantes atingido")
        now=datetime.now(UTC).timestamp(); activity=[t for t in _room_activity.get(u.id,[]) if now-t<60]
        if len(activity)>=int(os.getenv("ROOM_INVITES_PER_MINUTE", "20")): raise HTTPException(429,"Limite de convites atingido")
        activity.append(now); _room_activity[u.id]=activity
        target=s.get(User,data.invitee_id)
        mutual=s.exec(select(Follow).where(Follow.follower_id==u.id,Follow.followed_id==data.invitee_id)).first() and s.exec(select(Follow).where(Follow.follower_id==data.invitee_id,Follow.followed_id==u.id)).first()
        if not target or target.banned or data.invitee_id==u.id or not mutual: raise HTTPException(403,"Convites exigem seguimento mútuo")
        if s.exec(select(RoomParticipant).where(RoomParticipant.room_id==room_id,RoomParticipant.user_id==data.invitee_id)).first(): raise HTTPException(409,"Usuário já participa da sala")
        existing=s.exec(select(RoomInvite).where(RoomInvite.room_id==room_id,RoomInvite.invitee_id==data.invitee_id,RoomInvite.status=="pending")).first()
        if existing: return {"id":str(existing.id),"status":"pending"}
        inv=RoomInvite(room_id=room_id,inviter_id=u.id,invitee_id=data.invitee_id); s.add(inv); s.add(Notification(recipient_id=data.invitee_id,actor_id=u.id,kind="room_invite",title="Convite para uma sala",body=f"{u.pseudonym} convidou você para a sala {room.title}.",url=f"/rooms/{room.id}")); s.commit(); return {"id":str(inv.id),"status":"pending"}
@app.post("/rooms/invites/{invite_id}/{decision}")
def decide_invite(invite_id: UUID, decision: str, u=Depends(current_user)):
    if decision not in {"accept","decline"}: raise HTTPException(400,"Decisão inválida")
    with Session(engine) as s:
        inv=s.get(RoomInvite,invite_id)
        if not inv or inv.invitee_id!=u.id or inv.status!="pending": raise HTTPException(404,"Convite não encontrado")
        inv.status="accepted" if decision=="accept" else "declined"; s.add(inv)
        if decision=="accept":
            s.add(RoomParticipant(room_id=inv.room_id,user_id=u.id,role="editor",accepted=True))
            room=s.get(WritingRoom,inv.room_id)
            if room and room.owner_id != u.id:
                s.add(Notification(recipient_id=room.owner_id,actor_id=u.id,kind="room_join",title="Convite aceito",body=f"{u.pseudonym} aceitou o convite para {room.title}.",url=f"/rooms/{room.id}"))
        s.commit(); return {"ok":True,"status":inv.status}
@app.get("/rooms/invites")
def room_invites(u=Depends(current_user)):
    with Session(engine) as s:
        rows=s.exec(select(RoomInvite).where(RoomInvite.invitee_id==u.id, RoomInvite.status=="pending").order_by(RoomInvite.created_at.desc())).all()
        return [{"id":str(i.id),"room_id":str(i.room_id),"room_title":(s.get(WritingRoom,i.room_id).title if s.get(WritingRoom,i.room_id) else "Sala"),"inviter_id":str(i.inviter_id),"inviter_pseudonym":(s.get(User,i.inviter_id).pseudonym if s.get(User,i.inviter_id) else "Pessoa Kayepad"),"created_at":i.created_at} for i in rows]

@app.get("/rooms/{room_id}/invites")
def room_outgoing_invites(room_id: UUID, u=Depends(current_user)):
    with Session(engine) as s:
        room=s.get(WritingRoom,room_id)
        if not room or room.owner_id!=u.id: raise HTTPException(403,"Sem permissão")
        rows=s.exec(select(RoomInvite).where(RoomInvite.room_id==room_id).order_by(RoomInvite.created_at.desc())).all()
        return [{"id":str(i.id),"invitee_id":str(i.invitee_id),"invitee_pseudonym":(s.get(User,i.invitee_id).pseudonym if s.get(User,i.invitee_id) else "Pessoa Kayepad"),"status":i.status,"created_at":i.created_at} for i in rows]

@app.get("/users/search")
def search_users(q: str = Query("", min_length=2, max_length=40), u=Depends(current_user)):
    term=q.strip().lower()
    if not term: return []
    with Session(engine) as s:
        rows=s.exec(select(User).where(User.pseudonym.ilike(f"%{term}%"), User.banned==False).limit(20)).all()
        return [{"id":str(x.id),"pseudonym":x.pseudonym} for x in rows if x.id != u.id]

@app.get("/rooms")
def list_rooms(u=Depends(current_user)):
    with Session(engine) as s:
        rooms=[s.get(WritingRoom,p.room_id) for p in s.exec(select(RoomParticipant).where(RoomParticipant.user_id==u.id,RoomParticipant.accepted==True)).all()]
        return [room_json(s,r) for r in rooms if r]
@app.get("/rooms/{room_id}")
def get_room(room_id: UUID,u=Depends(current_user)):
    with Session(engine) as s:
        room=s.get(WritingRoom,room_id)
        if not room or not room_member(s,room_id,u.id): raise HTTPException(404,"Sala não encontrada")
        return room_json(s,room)
@app.patch("/rooms/{room_id}/participants/{user_id}")
def set_room_permission(room_id:UUID,user_id:UUID,data:PermissionIn,u=Depends(current_user)):
    if data.role not in {"editor","viewer"}: raise HTTPException(400,"Permissão inválida")
    with Session(engine) as s:
        room=s.get(WritingRoom,room_id); p=s.exec(select(RoomParticipant).where(RoomParticipant.room_id==room_id,RoomParticipant.user_id==user_id)).first()
        if not room or room.owner_id!=u.id or not p or user_id==room.owner_id: raise HTTPException(403,"Sem permissão")
        p.role=data.role; s.add(p); s.commit(); return {"user_id":str(user_id),"role":p.role}
@app.post("/rooms/{room_id}/close")
def close_room(room_id:UUID,u=Depends(current_user)):
    with Session(engine) as s:
        room=s.get(WritingRoom,room_id)
        if not room or room.owner_id!=u.id: raise HTTPException(403,"Sem permissão")
        room.status="closed"; room.closed_at=datetime.now(UTC); s.add(room); s.commit(); return {"ok":True,"status":"closed"}
@app.websocket("/rooms/{room_id}/ws")
async def room_ws(websocket: WebSocket, room_id: UUID):
    token=websocket.query_params.get("token",""); user_id=None
    if token:
        with Session(engine) as s:
            st=s.exec(select(SessionToken).where(SessionToken.token_hash==hashlib.sha256(token.encode()).hexdigest(),SessionToken.revoked==False)).first()
            if st and (st.expires_at.replace(tzinfo=UTC) if st.expires_at.tzinfo is None else st.expires_at)>datetime.now(UTC) and room_member(s,room_id,st.user_id): user_id=st.user_id
    if not user_id: await websocket.close(code=4403); return
    await websocket.accept(); key=str(room_id); _room_connections.setdefault(key,set()).add(websocket); times=[]
    try:
        while True:
            text_message=await websocket.receive_text()
            now=asyncio.get_running_loop().time(); times=[t for t in times if now-t<10]
            if len(text_message.encode())>4096 or len(times)>=30: await websocket.close(code=4429); break
            times.append(now)
            # Relay metadata/content opaquely; never write message content to storage.
            packet=json.loads(text_message)
            if not isinstance(packet,dict): continue
            packet={"type":str(packet.get("type","signal"))[:32],"from":str(user_id),"data":packet.get("data",{})}
            for peer in list(_room_connections.get(key,set())):
                if peer is not websocket:
                    try: await peer.send_json(packet)
                    except Exception: _room_connections[key].discard(peer)
    except (WebSocketDisconnect, json.JSONDecodeError): pass
    finally:
        _room_connections.get(key,set()).discard(websocket)

class OfficialUpdate(BaseModel):
    title:str=PField(min_length=1,max_length=160); body:str=PField(min_length=1,max_length=1000); url:str=PField(default="",max_length=500)
@app.get("/admin", response_class=HTMLResponse)
def admin_page(_=Depends(admin_key)):
    # Deliberately lives on the API origin and is never linked or copied to Neocities.
    return HTMLResponse("""<!doctype html><meta charset='utf-8'><title>Kayepad · Administração</title><style>body{font:16px system-ui;max-width:760px;margin:48px auto;padding:20px;color:#201a35}h1{color:#41258f}code{background:#f0ecfa;padding:3px 6px;border-radius:4px}</style><h1>Kayepad · Administração</h1><p>Área protegida. Use a API autenticada para usuários, moderação, auditoria e controles de privacidade.</p><p>Endpoints: <code>GET /admin/users</code> · <code>GET /admin/audit</code> · <code>GET /admin/rate-controls</code></p>""")

@app.get("/admin/audit")
def admin_audit(limit:int=Query(100,ge=1,le=500),_=Depends(admin_key)):
    with Session(engine) as s:
        return [{"action":e.action,"target_id":str(e.target_id) if e.target_id else None,"actor":e.actor,"ip_hash":e.ip_hash,"created_at":e.created_at} for e in s.exec(select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)).all()]

@app.get("/admin/rate-controls")
def admin_rate_controls(_=Depends(admin_key)):
    # Counts only: no raw address or identifying request history is exposed.
    return {"active_buckets":len(_requests),"limit_per_minute":int(os.getenv("RATE_LIMIT_PER_MINUTE","120")),"ip_storage":"keyed_sha256_only"}

@app.post("/admin/official/notify")
def official_notify(data:OfficialUpdate,_=Depends(admin_key)): 
    with Session(engine) as s:
        official=provision_official(s)
        users=s.exec(select(User).where(User.id!=official.id,User.banned==False)).all()
        for user in users: s.add(Notification(recipient_id=user.id,actor_id=official.id,kind="official",title=data.title,body=data.body,url=data.url))
        s.commit(); return {"sent":len(users)}
@app.post("/admin/users/{user_id}/badge")
def set_badge(user_id:UUID,data:BadgeIn,_=Depends(admin_key)):
    if data.badge not in {"normal","support","ambassador","partner","verified","official_gold"}: raise HTTPException(400,"Selo inválido")
    with Session(engine) as s:
        u=s.get(User,user_id)
        if not u: raise HTTPException(404,"Usuário não encontrado")
        u.badge=data.badge; s.add(u); s.commit(); return {"id":str(u.id),"badge":u.badge}
@app.post("/admin/users/{user_id}/verify-email")
def verify_email(user_id:UUID,_=Depends(admin_key)):
    with Session(engine) as s:
        u=s.get(User,user_id)
        if not u: raise HTTPException(404,"Usuário não encontrado")
        u.email_verified=True; s.add(u); s.commit(); refresh_verified(s,u); return public_user(u)
@app.post("/admin/comments/{comment_id}/hide")
def hide_comment(comment_id:UUID,request:Request,_=Depends(admin_key)):
    with Session(engine) as s:
        c=s.get(Comment,comment_id)
        if not c: raise HTTPException(404,"Comentário não encontrado")
        c.hidden=True; s.add(c); audit(s,"comment.hide",c.id,request); s.commit(); return {"id":str(c.id),"hidden":True}
@app.post("/admin/users/{user_id}/ban")
def ban(user_id:UUID,request:Request,_=Depends(admin_key)):
    with Session(engine) as s:
        u=s.get(User,user_id)
        if not u: raise HTTPException(404,"Usuário não encontrado")
        u.banned=True; s.add(u); audit(s,"user.ban",u.id,request); s.commit(); return {"id":str(u.id),"banned":True}
@app.get("/admin/users")
def admin_users(_=Depends(admin_key)):
    with Session(engine) as s: return [public_user(u) for u in s.exec(select(User).order_by(User.created_at.desc())).all()]
@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    messages=[]
    for err in exc.errors():
        loc=err.get("loc",[]); msg=str(err.get("msg","Dados inválidos"))
        field=loc[-1] if loc else "campo"
        if field=="password" and "maiúscula" in msg:
            msg="A senha deve ter pelo menos 10 caracteres, incluindo uma letra maiúscula, uma letra minúscula e um número."
        elif msg.startswith("Value error, "): msg=msg[13:]
        elif err.get("type")=="value_error.email": msg="Informe um e-mail válido."
        elif err.get("type")=="string_too_short": msg=f"O campo {field} está curto demais."
        messages.append(msg)
    return JSONResponse({"detail":" ".join(dict.fromkeys(messages)) or "Confira os dados informados."},status_code=422,headers={"X-Content-Type-Options":"nosniff"})
@app.exception_handler(Exception)
async def unhandled(request, exc):
    return JSONResponse({"detail":"Erro interno do servidor"},status_code=500)
