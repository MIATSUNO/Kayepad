import os
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import bcrypt
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as DBField, Session, select

from app import app, engine, KUser, KPost, KSession, me

UTC = timezone.utc
QUESTIONS = {2: 'Ig&x kaye?', 3: 'Mokolo mpe sanza?', 4: 'código de acesso?'}


class KAdminChallenge(SQLModel, table=True):
    __tablename__ = 'kt_admin_challenges'
    id: UUID = DBField(default_factory=uuid4, primary_key=True)
    challenge_hash: str = DBField(unique=True, index=True)
    user_id: UUID = DBField(index=True)
    primary_session_hash: str = DBField(index=True)
    step: int = 2
    attempts: int = 0
    expires_at: datetime
    created_at: datetime = DBField(default_factory=lambda: datetime.now(UTC))
    consumed: bool = False


class KAdminSession(SQLModel, table=True):
    __tablename__ = 'kt_admin_sessions'
    id: UUID = DBField(default_factory=uuid4, primary_key=True)
    token_hash: str = DBField(unique=True, index=True)
    user_id: UUID = DBField(index=True)
    primary_session_hash: str = DBField(index=True)
    expires_at: datetime
    revoked: bool = False


class AdminAnswerIn(BaseModel):
    challenge: str = Field(min_length=32, max_length=160)
    answer: str = Field(min_length=1, max_length=256)


def admin_ids():
    return {value.strip() for value in os.getenv('KAYSTANT_ADMIN_USER_IDS', '').split(',') if value.strip()}


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_allowlisted(user):
    allowed = admin_ids()
    if not allowed:
        raise HTTPException(503, 'Painel administrativo não configurado')
    if str(user.id) not in allowed:
        raise HTTPException(403, 'Acesso administrativo não autorizado')


def _bearer_hash(authorization):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Faça login para continuar')
    return hashlib.sha256(authorization[7:].encode()).hexdigest()


def _mfa_hashes_configured():
    return all(os.getenv(name, '').strip() for name in (
        'KAYSTANT_ADMIN_STEP2_BCRYPT_HASH',
        'KAYSTANT_ADMIN_STEP3_SCRYPT_HASH',
        'KAYSTANT_ADMIN_STEP4_PBKDF2_HASH',
    ))


def _verify_answer(step, answer):
    raw = answer.strip().encode('utf-8')
    try:
        if step == 2:
            encoded = os.getenv('KAYSTANT_ADMIN_STEP2_BCRYPT_HASH', '').encode()
            return bool(encoded) and bcrypt.checkpw(raw, encoded)
        if step == 3:
            parts = os.getenv('KAYSTANT_ADMIN_STEP3_SCRYPT_HASH', '').split('$')
            if len(parts) != 6 or parts[0] != 'scrypt':
                return False
            _, n_text, r_text, p_text, salt_hex, digest_hex = parts
            digest = hashlib.scrypt(raw, salt=bytes.fromhex(salt_hex), n=int(n_text), r=int(r_text), p=int(p_text), dklen=len(bytes.fromhex(digest_hex)))
            return hmac.compare_digest(digest.hex(), digest_hex)
        if step == 4:
            parts = os.getenv('KAYSTANT_ADMIN_STEP4_PBKDF2_HASH', '').split('$')
            if len(parts) != 4 or parts[0] != 'pbkdf2-sha256':
                return False
            _, iterations_text, salt_hex, digest_hex = parts
            digest = hashlib.pbkdf2_hmac('sha256', raw, bytes.fromhex(salt_hex), int(iterations_text), dklen=len(bytes.fromhex(digest_hex)))
            return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, TypeError, OverflowError):
        return False
    return False


def _utc_now():
    return datetime.now(UTC)


@app.post('/admin/step-up/start')
def admin_step_up_start(authorization: str | None = Header(None), user=Depends(me)):
    _require_allowlisted(user)
    if not _mfa_hashes_configured():
        raise HTTPException(503, 'Verificação administrativa indisponível')
    primary_hash = _bearer_hash(authorization)
    now = _utc_now()
    challenge = secrets.token_urlsafe(32)
    with Session(engine) as session:
        recent = session.exec(select(KAdminChallenge).where(
            KAdminChallenge.user_id == user.id,
            KAdminChallenge.created_at >= now - timedelta(minutes=15),
        )).all()
        if len(recent) >= 3:
            raise HTTPException(429, 'Muitas tentativas de acesso administrativo. Aguarde 15 minutos.')
        active = session.exec(select(KAdminChallenge).where(
            KAdminChallenge.primary_session_hash == primary_hash,
            KAdminChallenge.consumed == False,
        )).all()
        for item in active:
            item.consumed = True
            session.add(item)
        session.add(KAdminChallenge(
            challenge_hash=hashlib.sha256(challenge.encode()).hexdigest(),
            user_id=user.id,
            primary_session_hash=primary_hash,
            step=2,
            expires_at=now + timedelta(minutes=10),
        ))
        session.commit()
    return {'challenge': challenge, 'step': 2, 'question': QUESTIONS[2], 'remaining': 3, 'expires_in': 600}


@app.post('/admin/step-up/answer')
def admin_step_up_answer(data: AdminAnswerIn, authorization: str | None = Header(None), user=Depends(me)):
    _require_allowlisted(user)
    primary_hash = _bearer_hash(authorization)
    challenge_hash = hashlib.sha256(data.challenge.encode()).hexdigest()
    now = _utc_now()
    with Session(engine) as session:
        challenge = session.exec(select(KAdminChallenge).where(
            KAdminChallenge.challenge_hash == challenge_hash,
            KAdminChallenge.user_id == user.id,
            KAdminChallenge.primary_session_hash == primary_hash,
            KAdminChallenge.consumed == False,
        ).with_for_update()).first()
        if not challenge or _utc(challenge.expires_at) <= now:
            raise HTTPException(401, 'Verificação expirada. Entre novamente.')
        if challenge.attempts >= 5:
            challenge.consumed = True
            session.add(challenge)
            session.commit()
            raise HTTPException(429, 'Limite de tentativas atingido. Entre novamente mais tarde.')
        if not _verify_answer(challenge.step, data.answer):
            challenge.attempts += 1
            if challenge.attempts >= 5:
                challenge.consumed = True
            session.add(challenge)
            session.commit()
            if challenge.attempts >= 5:
                raise HTTPException(429, 'Limite de tentativas atingido. Entre novamente mais tarde.')
            raise HTTPException(401, 'Resposta incorreta. Tente novamente.')
        challenge.step += 1
        challenge.attempts = 0
        if challenge.step <= 4:
            session.add(challenge)
            session.commit()
            return {'step': challenge.step, 'question': QUESTIONS[challenge.step], 'remaining': 5 - challenge.step}
        challenge.consumed = True
        admin_token = secrets.token_urlsafe(48)
        active_admin_sessions = session.exec(select(KAdminSession).where(
            KAdminSession.user_id == user.id,
            KAdminSession.revoked == False,
        )).all()
        for item in active_admin_sessions:
            item.revoked = True
            session.add(item)
        session.add(challenge)
        session.add(KAdminSession(
            token_hash=hashlib.sha256(admin_token.encode()).hexdigest(),
            user_id=user.id,
            primary_session_hash=primary_hash,
            expires_at=now + timedelta(minutes=15),
        ))
        session.commit()
    return {'completed': True, 'admin_token': admin_token, 'expires_in': 900, 'remaining': 0}


def admin_required(authorization: str | None = Header(None)):
    token_hash = _bearer_hash(authorization)
    now = _utc_now()
    with Session(engine) as session:
        admin_session = session.exec(select(KAdminSession).where(
            KAdminSession.token_hash == token_hash,
            KAdminSession.revoked == False,
        )).first()
        if not admin_session or _utc(admin_session.expires_at) <= now:
            raise HTTPException(401, 'Verificação administrativa ausente ou expirada')
        primary_session = session.exec(select(KSession).where(
            KSession.token_hash == admin_session.primary_session_hash,
            KSession.revoked == False,
        )).first()
        user = session.get(KUser, admin_session.user_id)
        if not primary_session or _utc(primary_session.expires_at) <= now or not user:
            raise HTTPException(401, 'Sessão expirada. Entre novamente.')
        if user.is_blocked:
            raise HTTPException(403, 'Esta conta está bloqueada')
        _require_allowlisted(user)
        return user


@app.get('/admin/users')
def admin_users(user=Depends(admin_required)):
    allowed_ids = admin_ids()
    with Session(engine) as session:
        users = session.exec(select(KUser).order_by(KUser.created_at.desc())).all()
        return [
            {
                'id': str(row.id),
                'username': row.username,
                'email': row.email,
                'created_at': row.created_at.isoformat() if row.created_at else None,
                'display_name': row.display_name,
                'bio': row.bio,
                'is_blocked': bool(row.is_blocked),
                'is_admin': str(row.id) in allowed_ids,
            }
            for row in users
        ]


@app.get('/admin/posts')
def admin_posts(user=Depends(admin_required)):
    with Session(engine) as session:
        posts = session.exec(select(KPost).order_by(KPost.created_at.desc())).all()
        result = []
        for post in posts:
            owner = session.get(KUser, post.user_id)
            result.append(
                {
                    'id': str(post.id),
                    'user_id': str(post.user_id),
                    'username': owner.username if owner else 'conta removida',
                    'title': post.title,
                    'created_at': post.created_at.isoformat() if post.created_at else None,
                }
            )
        return result
