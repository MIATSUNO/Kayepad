import json, hashlib, re
from datetime import datetime, timedelta
from urllib.parse import urlparse
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field as DBField, Session, select
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException
from app import app, engine, me, KUser, UTC

class KDelivery(SQLModel, table=True):
    __tablename__ = 'kt_kayepad_deliveries'
    id: UUID = DBField(default_factory=uuid4, primary_key=True)
    sender_id: UUID = DBField(index=True)
    recipient_id: UUID = DBField(index=True)
    title: str
    author: str
    synopsis: str = ''
    cover_url: str = ''
    book_json: str
    work_hash: str = DBField(index=True)
    status: str = 'pending'
    created_at: datetime = DBField(default_factory=lambda: datetime.now(UTC))
    accepted_at: datetime | None = None
    returned_at: datetime | None = None

class KDeliveryFeedback(SQLModel, table=True):
    __tablename__ = 'kt_kayepad_delivery_feedback'
    id: UUID = DBField(default_factory=uuid4, primary_key=True)
    delivery_id: UUID = DBField(index=True, unique=True)
    rating: int
    reaction: str
    created_at: datetime = DBField(default_factory=lambda: datetime.now(UTC))

class KDeliveryNotice(SQLModel, table=True):
    __tablename__ = 'kt_kayepad_delivery_notices'
    id: UUID = DBField(default_factory=uuid4, primary_key=True)
    user_id: UUID = DBField(index=True)
    kind: str
    delivery_id: UUID = DBField(index=True)
    message: str
    created_at: datetime = DBField(default_factory=lambda: datetime.now(UTC))
    read: bool = False

class DeliveryIn(BaseModel):
    recipient_username: str = Field(min_length=3, max_length=40, pattern=r'^[A-Za-z0-9_.-]+$')
    book: dict
    synopsis: str = Field(default='', max_length=1200)
    cover_url: str = Field(default='', max_length=1000)

class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    reaction: str

ALLOWED_REACTIONS = {'😍 Amei', '🥺 Emocionante', '🤯 Viciante'}
MAX_PAYLOAD = 12 * 1024 * 1024


def clean_book(raw):
    if not isinstance(raw, dict):
        raise HTTPException(422, 'Obra inválida')
    chapters = raw.get('chapters')
    if not isinstance(chapters, list) or not chapters or len(chapters) > 10000:
        raise HTTPException(422, 'A obra precisa ter capítulos')
    cleaned = []
    for i, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            continue
        title = chapter.get('title', '')
        content = chapter.get('content', '')
        if not isinstance(title, str) or not isinstance(content, str):
            raise HTTPException(422, 'Capítulo inválido')
        cleaned.append({'title': (title.strip() or f'Capítulo {i + 1}')[:300], 'content': content})
    if not cleaned:
        raise HTTPException(422, 'A obra precisa ter capítulos')
    title = raw.get('title') or 'Obra sem título'
    author = raw.get('author') or 'Autor Kaye'
    if not isinstance(title, str) or not isinstance(author, str):
        raise HTTPException(422, 'Título ou autoria inválidos')
    book = {
        'type': 'BOOK',
        'title': title.strip()[:300] or 'Obra sem título',
        'author': author.strip()[:200] or 'Autor Kaye',
        'chapters': cleaned,
    }
    encoded = json.dumps(book, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    if len(encoded) > MAX_PAYLOAD:
        raise HTTPException(413, 'A obra excede 12 MB')
    canonical = '\n'.join(
        [book['title'].casefold(), book['author'].casefold()]
        + [chapter['title'] + '\n' + chapter['content'] for chapter in cleaned]
    )
    return book, hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def safe_cover_url(value):
    value = (value or '').strip()
    if not value:
        return ''
    parsed = urlparse(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, 'A capa precisa usar uma URL HTTPS pública')
    if any(ord(char) < 32 for char in value):
        raise HTTPException(422, 'URL de capa inválida')
    return value


def delivery_json(delivery, sender=None, recipient=None, include_book=False, feedback=None):
    result = {
        'id': str(delivery.id),
        'sender_username': sender.username if sender else '',
        'recipient_username': recipient.username if recipient else '',
        'title': delivery.title,
        'author': delivery.author,
        'synopsis': delivery.synopsis,
        'cover_url': delivery.cover_url,
        'status': delivery.status,
        'created_at': delivery.created_at.isoformat(),
        'accepted_at': delivery.accepted_at.isoformat() if delivery.accepted_at else None,
        'returned_at': delivery.returned_at.isoformat() if delivery.returned_at else None,
    }
    if include_book:
        result['book'] = json.loads(delivery.book_json)
    if feedback:
        result['feedback'] = {
            'rating': feedback.rating,
            'reaction': feedback.reaction,
            'created_at': feedback.created_at.isoformat(),
        }
    return result


@app.post('/social/deliveries')
def send_delivery(data: DeliveryIn, user=Depends(me)):
    book, work_hash = clean_book(data.book)
    cover_url = safe_cover_url(data.cover_url)
    with Session(engine) as session:
        # Serialize sends by the same account so concurrent duplicate requests
        # cannot bypass the 24-hour check on PostgreSQL.
        sender = session.exec(select(KUser).where(KUser.id == user.id).with_for_update()).first()
        recipient = session.exec(select(KUser).where(KUser.username == data.recipient_username)).first()
        if not sender or not recipient:
            raise HTTPException(404, 'Usuário não encontrado')
        if recipient.id == sender.id:
            raise HTTPException(400, 'Você não pode enviar uma obra para si')
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        previous = session.exec(
            select(KDelivery).where(
                KDelivery.sender_id == sender.id,
                KDelivery.recipient_id == recipient.id,
                KDelivery.work_hash == work_hash,
                KDelivery.created_at >= cutoff,
            )
        ).first()
        if previous:
            raise HTTPException(429, 'Você já enviou esta obra para esse usuário nas últimas 24 horas')
        delivery = KDelivery(
            sender_id=sender.id,
            recipient_id=recipient.id,
            title=book['title'],
            author=book['author'],
            synopsis=data.synopsis.strip(),
            cover_url=cover_url,
            book_json=json.dumps(book, ensure_ascii=False, separators=(',', ':')),
            work_hash=work_hash,
        )
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
        return delivery_json(delivery, sender, recipient)


@app.get('/social/inbox')
def delivery_inbox(user=Depends(me)):
    with Session(engine) as session:
        deliveries = session.exec(
            select(KDelivery)
            .where(KDelivery.recipient_id == user.id)
            .order_by(KDelivery.created_at.desc())
            .limit(100)
        ).all()
        return [
            delivery_json(
                delivery,
                session.get(KUser, delivery.sender_id),
                user,
                feedback=session.exec(
                    select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id == delivery.id)
                ).first(),
            )
            for delivery in deliveries
        ]


@app.get('/social/deliveries/{delivery_id}/book')
def received_book(delivery_id: UUID, user=Depends(me)):
    with Session(engine) as session:
        delivery = session.get(KDelivery, delivery_id)
        if not delivery or delivery.recipient_id != user.id:
            raise HTTPException(404, 'Pacote não encontrado')
        if delivery.status == 'pending':
            raise HTTPException(409, 'Aceite o pacote para colocar a obra em Vias')
        if delivery.status == 'returned':
            raise HTTPException(410, 'A obra já foi devolvida')
        return delivery_json(
            delivery,
            session.get(KUser, delivery.sender_id),
            user,
            include_book=True,
            feedback=session.exec(
                select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id == delivery.id)
            ).first(),
        )


@app.post('/social/deliveries/{delivery_id}/accept')
def accept_delivery(delivery_id: UUID, user=Depends(me)):
    with Session(engine) as session:
        delivery = session.get(KDelivery, delivery_id)
        if not delivery or delivery.recipient_id != user.id:
            raise HTTPException(404, 'Pacote não encontrado')
        if delivery.status == 'returned':
            raise HTTPException(409, 'Este pacote já foi devolvido')
        if delivery.status == 'pending':
            delivery.status = 'accepted'
            delivery.accepted_at = datetime.now(UTC)
            session.add(delivery)
            session.commit()
            session.refresh(delivery)
        return delivery_json(delivery, session.get(KUser, delivery.sender_id), user, include_book=True)


@app.post('/social/deliveries/{delivery_id}/feedback')
def feedback_delivery(delivery_id: UUID, data: FeedbackIn, user=Depends(me)):
    if data.reaction not in ALLOWED_REACTIONS:
        raise HTTPException(422, 'Reação inválida')
    with Session(engine) as session:
        delivery = session.get(KDelivery, delivery_id)
        if not delivery or delivery.recipient_id != user.id:
            raise HTTPException(404, 'Pacote não encontrado')
        if delivery.status == 'returned':
            raise HTTPException(409, 'Pacote devolvido')
        existing = session.exec(
            select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id == delivery.id)
        ).first()
        if existing:
            raise HTTPException(409, 'Feedback já enviado')
        feedback = KDeliveryFeedback(
            delivery_id=delivery.id,
            rating=data.rating,
            reaction=data.reaction,
        )
        owner = session.get(KUser, delivery.sender_id)
        if not owner:
            raise HTTPException(404, 'Pessoa autora não encontrada')
        message = (
            f'⭐ Feedback em "{delivery.title}"\n'
            f'KayepadOficial • via @{user.username}\n\n'
            f'{data.reaction}\n\n'
            f'Olá @{owner.username}, você recebeu um feedback de @{user.username}: {data.rating} estrelas!'
        )
        session.add(feedback)
        session.add(KDeliveryNotice(
            user_id=delivery.sender_id,
            kind='feedback',
            delivery_id=delivery.id,
            message=message,
        ))
        session.commit()
        return {'ok': True, 'feedback': {'rating': feedback.rating, 'reaction': feedback.reaction}}


@app.post('/social/deliveries/{delivery_id}/return')
def return_delivery(delivery_id: UUID, user=Depends(me)):
    with Session(engine) as session:
        delivery = session.get(KDelivery, delivery_id)
        if not delivery or delivery.recipient_id != user.id:
            raise HTTPException(404, 'Pacote não encontrado')
        if delivery.status != 'accepted' or not delivery.accepted_at:
            raise HTTPException(409, 'Aceite primeiro este pacote')
        accepted_at = delivery.accepted_at
        if accepted_at.tzinfo is None:
            accepted_at = accepted_at.replace(tzinfo=UTC)
        if datetime.now(UTC) < accepted_at + timedelta(days=7):
            raise HTTPException(409, 'A obra poderá ser devolvida após 7 dias do aceite')
        recipient = session.get(KUser, delivery.recipient_id)
        sender = session.get(KUser, delivery.sender_id)
        if not sender or not recipient:
            raise HTTPException(404, 'Conta associada ao pacote não encontrada')
        delivery.status = 'returned'
        delivery.returned_at = datetime.now(UTC)
        session.add(delivery)
        session.add(KDeliveryNotice(
            user_id=delivery.sender_id,
            kind='return',
            delivery_id=delivery.id,
            message=f'📚 "{delivery.title}" foi devolvida por @{recipient.username}',
        ))
        session.commit()
        session.refresh(delivery)
        return delivery_json(delivery, sender, recipient)


@app.get('/social/notifications')
def delivery_notifications(user=Depends(me)):
    with Session(engine) as session:
        notices = session.exec(
            select(KDeliveryNotice)
            .where(KDeliveryNotice.user_id == user.id)
            .order_by(KDeliveryNotice.created_at.desc())
            .limit(100)
        ).all()
        return [
            {
                'id': str(notice.id),
                'kind': notice.kind,
                'delivery_id': str(notice.delivery_id),
                'message': notice.message,
                'created_at': notice.created_at.isoformat(),
                'read': notice.read,
            }
            for notice in notices
        ]


@app.post('/social/notifications/{notice_id}/read')
def mark_delivery_notice_read(notice_id: UUID, user=Depends(me)):
    with Session(engine) as session:
        notice = session.get(KDeliveryNotice, notice_id)
        if not notice or notice.user_id != user.id:
            raise HTTPException(404, 'Notificação não encontrada')
        if not notice.read:
            notice.read = True
            session.add(notice)
            session.commit()
        return {'ok': True, 'read': True}
