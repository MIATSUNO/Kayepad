import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import HTTPException, Header
from pydantic import BaseModel, Field
from sqlalchemy import text, update
from sqlmodel import select
from app import app, Session, engine, KUser, KSession, pw


class RecoverIn(BaseModel):
    email: str = Field(pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class KaystantRecoverIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=100)
    email: str = Field(pattern=r'^[^@\s]+@kaystant\.org$')
    username: str = Field(min_length=3, max_length=40)


class ResetIn(BaseModel):
    token: str = Field(min_length=32)
    password: str = Field(min_length=8, max_length=128)


class OwnerResetIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=128)


@app.post('/auth/recover')
def recover(d: RecoverIn):
    raise HTTPException(503, 'A recuperação automática ainda não está ligada a um email verificado. Entre em contato com o suporte.')


@app.post('/auth/recover-kaystant')
def recover_kaystant(d: KaystantRecoverIn):
    raise HTTPException(503, 'A recuperação segura desta conta ainda não está disponível. Entre em contato com o suporte.')


@app.post('/auth/reset-password')
def reset_password(d: ResetIn):
    if os.getenv('KAYSTANT_VERIFIED_RESET_FLOW', '').lower() != 'true':
        raise HTTPException(503, 'A redefinição segura desta conta ainda não está disponível. Entre em contato com o suporte.')
    token_hash = hashlib.sha256(d.token.encode()).hexdigest()
    with Session(engine) as session:
        row = session.execute(
            text('SELECT id,user_id,expires_at,used FROM kt_password_resets WHERE token_hash=:token_hash'),
            {'token_hash': token_hash},
        ).mappings().first()
        expires_at = row['expires_at'] if row else None
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
        if expires_at is not None and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not row or row['used'] or expires_at < datetime.now(timezone.utc):
            raise HTTPException(400, 'Código de recuperação inválido ou expirado')
        claimed = session.execute(
            text('UPDATE kt_password_resets SET used=TRUE WHERE id=:id AND used=FALSE'),
            {'id': row['id']},
        )
        if claimed.rowcount != 1:
            raise HTTPException(400, 'Código de recuperação inválido ou expirado')
        user = session.get(KUser, UUID(str(row['user_id'])))
        if not user:
            raise HTTPException(400, 'Código de recuperação inválido ou expirado')
        user.password_hash = pw(d.password)
        session.execute(update(KSession).where(KSession.user_id == user.id).values(revoked=True))
        session.commit()
    return {'reset': True}


@app.post('/auth/owner-reset-once', include_in_schema=False)
def owner_reset_once(data: OwnerResetIn, x_reset_token: str | None = Header(None, alias='X-Kayepad-Recovery')):
    expected = os.getenv('KAYSTANT_OWNER_RESET_TOKEN_HASH', '')
    if not expected or not x_reset_token:
        raise HTTPException(404, 'Not found')
    token_hash = hashlib.sha256(x_reset_token.encode()).hexdigest()
    if not hmac.compare_digest(expected, token_hash):
        raise HTTPException(404, 'Not found')
    email = data.email.strip().lower()
    if email != 'kayepad.bird@gmail.com':
        raise HTTPException(404, 'Not found')
    now = datetime.now(timezone.utc)
    with Session(engine) as session:
        user = session.exec(select(KUser).where(KUser.email == email)).first()
        if not user:
            raise HTTPException(404, 'Not found')
        existing = session.execute(
            text('SELECT id FROM kt_password_resets WHERE token_hash=:token_hash'),
            {'token_hash': token_hash},
        ).first()
        if existing:
            raise HTTPException(409, 'This reset was already used')
        session.execute(
            text('INSERT INTO kt_password_resets (id,user_id,token_hash,expires_at,used) VALUES (:id,:user_id,:token_hash,:expires_at,FALSE)'),
            {'id': secrets.token_hex(16), 'user_id': str(user.id), 'token_hash': token_hash, 'expires_at': now + timedelta(minutes=15)},
        )
        user.password_hash = pw(data.password)
        session.add(user)
        session.execute(update(KSession).where(KSession.user_id == user.id).values(revoked=True))
        session.execute(text('UPDATE kt_admin_sessions SET revoked=TRUE WHERE user_id=:user_id'), {'user_id': str(user.id)})
        session.execute(text('UPDATE kt_admin_challenges SET consumed=TRUE WHERE user_id=:user_id AND consumed=FALSE'), {'user_id': str(user.id)})
        claimed = session.execute(
            text('UPDATE kt_password_resets SET used=TRUE WHERE token_hash=:token_hash AND used=FALSE'),
            {'token_hash': token_hash},
        )
        if claimed.rowcount != 1:
            raise HTTPException(409, 'This reset was already used')
        session.commit()
    os.environ.pop('KAYSTANT_OWNER_RESET_TOKEN_HASH', None)
    return {'reset': True}
