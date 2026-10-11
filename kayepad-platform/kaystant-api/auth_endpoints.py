import os
import hashlib
from datetime import datetime, timezone
from uuid import UUID
from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text, update
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
        user = session.get(KUser, UUID(str(row['user_id'])))
        if not user:
            raise HTTPException(400, 'Código de recuperação inválido ou expirado')
        user.password_hash = pw(d.password)
        session.execute(text('UPDATE kt_password_resets SET used=TRUE WHERE id=:id'), {'id': row['id']})
        session.execute(update(KSession).where(KSession.user_id == user.id).values(revoked=True))
        session.commit()
    return {'reset': True}
