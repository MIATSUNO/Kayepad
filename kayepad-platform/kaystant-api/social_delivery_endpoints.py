import json, hashlib, re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from sqlmodel import SQLModel, Field as DBField, Session, select
from pydantic import BaseModel, Field
from fastapi import Depends, HTTPException
from app import app, engine, me, KUser, UTC

class KDelivery(SQLModel, table=True):
    __tablename__='kt_kayepad_deliveries'
    id: UUID=DBField(default_factory=uuid4, primary_key=True)
    sender_id: UUID=DBField(index=True)
    recipient_id: UUID=DBField(index=True)
    title: str
    author: str
    synopsis: str=''
    cover_url: str=''
    book_json: str
    work_hash: str=DBField(index=True)
    status: str='pending'
    created_at: datetime=DBField(default_factory=lambda:datetime.now(UTC))
    accepted_at: datetime|None=None
    returned_at: datetime|None=None

class KDeliveryFeedback(SQLModel, table=True):
    __tablename__='kt_kayepad_delivery_feedback'
    id: UUID=DBField(default_factory=uuid4, primary_key=True)
    delivery_id: UUID=DBField(index=True, unique=True)
    rating: int
    reaction: str
    created_at: datetime=DBField(default_factory=lambda:datetime.now(UTC))

class KDeliveryNotice(SQLModel, table=True):
    __tablename__='kt_kayepad_delivery_notices'
    id: UUID=DBField(default_factory=uuid4, primary_key=True)
    user_id: UUID=DBField(index=True)
    kind: str
    delivery_id: UUID=DBField(index=True)
    message: str
    created_at: datetime=DBField(default_factory=lambda:datetime.now(UTC))
    read: bool=False

class DeliveryIn(BaseModel):
    recipient_username: str=Field(min_length=3,max_length=40,pattern=r'^[A-Za-z0-9_.-]+$')
    book: dict
    synopsis: str=Field(default='',max_length=1200)
    cover_url: str=Field(default='',max_length=1000)

class FeedbackIn(BaseModel):
    rating: int=Field(ge=1,le=5)
    reaction: str

ALLOWED_REACTIONS={'😍 Amei','🥺 Emocionante','🤯 Viciante'}
MAX_PAYLOAD=12*1024*1024

def clean_book(raw):
    if not isinstance(raw,dict): raise HTTPException(422,'Obra inválida')
    chapters=raw.get('chapters')
    if not isinstance(chapters,list) or not chapters or len(chapters)>10000: raise HTTPException(422,'A obra precisa ter capítulos')
    cleaned=[]
    for i,ch in enumerate(chapters):
        if not isinstance(ch,dict): continue
        cleaned.append({'title':str(ch.get('title') or f'Capítulo {i+1}')[:300], 'content':str(ch.get('content') or '')})
    if not cleaned: raise HTTPException(422,'A obra precisa ter capítulos')
    book={'type':'BOOK','title':str(raw.get('title') or 'Obra sem título').strip()[:300], 'author':str(raw.get('author') or 'Autor Kaye').strip()[:200], 'chapters':cleaned}
    if len(json.dumps(book,ensure_ascii=False).encode())>MAX_PAYLOAD: raise HTTPException(413,'A obra excede 12 MB')
    canon='\n'.join([book['title'].casefold(),book['author'].casefold()]+[c['title']+'\n'+c['content'] for c in cleaned])
    return book,hashlib.sha256(canon.encode()).hexdigest()

def delivery_json(d, sender=None, recipient=None, include_book=False, feedback=None):
    out={'id':str(d.id),'sender_username':sender.username if sender else '', 'recipient_username':recipient.username if recipient else '', 'title':d.title,'author':d.author,'synopsis':d.synopsis,'cover_url':d.cover_url,'status':d.status,'created_at':d.created_at.isoformat(),'accepted_at':d.accepted_at.isoformat() if d.accepted_at else None,'returned_at':d.returned_at.isoformat() if d.returned_at else None}
    if include_book: out['book']=json.loads(d.book_json)
    if feedback: out['feedback']={'rating':feedback.rating,'reaction':feedback.reaction,'created_at':feedback.created_at.isoformat()}
    return out

@app.post('/social/deliveries')
def send_delivery(d:DeliveryIn,u=Depends(me)):
    book,work_hash=clean_book(d.book)
    with Session(engine) as s:
        recipient=s.exec(select(KUser).where(KUser.username==d.recipient_username)).first()
        if not recipient: raise HTTPException(404,'Usuário não encontrado')
        if recipient.id==u.id: raise HTTPException(400,'Você não pode enviar uma obra para si')
        since=datetime.now(UTC)-timedelta(hours=24)
        prior=s.exec(select(KDelivery).where(KDelivery.sender_id==u.id,KDelivery.recipient_id==recipient.id,KDelivery.work_hash==work_hash,KDelivery.created_at>=since)).first()
        if prior: raise HTTPException(429,'Você já enviou esta obra para esse usuário nas últimas 24 horas')
        row=KDelivery(sender_id=u.id,recipient_id=recipient.id,title=book['title'],author=book['author'],synopsis=d.synopsis,cover_url=d.cover_url,book_json=json.dumps(book,ensure_ascii=False,separators=(',',':')),work_hash=work_hash)
        s.add(row);s.commit();s.refresh(row)
        return delivery_json(row,u,recipient)

@app.get('/social/inbox')
def delivery_inbox(u=Depends(me)):
    with Session(engine) as s:
        rows=s.exec(select(KDelivery).where(KDelivery.recipient_id==u.id).order_by(KDelivery.created_at.desc()).limit(100)).all()
        return [delivery_json(x,s.get(KUser,x.sender_id),u,feedback=s.exec(select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id==x.id)).first()) for x in rows]

@app.post('/social/deliveries/{delivery_id}/accept')
def accept_delivery(delivery_id:UUID,u=Depends(me)):
    with Session(engine) as s:
        row=s.get(KDelivery,delivery_id)
        if not row or row.recipient_id!=u.id: raise HTTPException(404,'Pacote não encontrado')
        if row.status=='returned': raise HTTPException(409,'Este pacote já foi devolvido')
        if row.status=='pending': row.status='accepted';row.accepted_at=datetime.now(UTC);s.add(row);s.commit();s.refresh(row)
        return delivery_json(row,s.get(KUser,row.sender_id),u,include_book=True)

@app.post('/social/deliveries/{delivery_id}/feedback')
def feedback_delivery(delivery_id:UUID,d:FeedbackIn,u=Depends(me)):
    if d.reaction not in ALLOWED_REACTIONS: raise HTTPException(422,'Reação inválida')
    with Session(engine) as s:
        row=s.get(KDelivery,delivery_id)
        if not row or row.recipient_id!=u.id: raise HTTPException(404,'Pacote não encontrado')
        if row.status=='returned': raise HTTPException(409,'Pacote devolvido')
        old=s.exec(select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id==row.id)).first()
        if old: raise HTTPException(409,'Feedback já enviado')
        f=KDeliveryFeedback(delivery_id=row.id,rating=d.rating,reaction=d.reaction);s.add(f)
        owner=s.get(KUser,row.sender_id)
        msg=f'⭐ Feedback em "{row.title}"\nKayepadOficial • via @{u.username}\n\n{d.reaction}\n\nOlá @{owner.username}, você recebeu um feedback de @{u.username}: {d.rating} estrelas!'
        s.add(KDeliveryNotice(user_id=row.sender_id,kind='feedback',delivery_id=row.id,message=msg));s.commit()
        return {'ok':True,'feedback':{'rating':f.rating,'reaction':f.reaction}}

@app.post('/social/deliveries/{delivery_id}/return')
def return_delivery(delivery_id:UUID,u=Depends(me)):
    with Session(engine) as s:
        row=s.get(KDelivery,delivery_id)
        if not row or row.recipient_id!=u.id: raise HTTPException(404,'Pacote não encontrado')
        if row.status!='accepted' or not row.accepted_at: raise HTTPException(409,'Aceite primeiro este pacote')
        accepted=row.accepted_at.replace(tzinfo=UTC) if row.accepted_at.tzinfo is None else row.accepted_at
        if datetime.now(UTC)<accepted+timedelta(days=7): raise HTTPException(409,'A obra poderá ser devolvida após 7 dias do aceite')
        row.status='returned';row.returned_at=datetime.now(UTC)
        sender=s.get(KUser,row.sender_id)
        s.add(KDeliveryNotice(user_id=row.sender_id,kind='return',delivery_id=row.id,message=f'📚 "{row.title}" foi devolvida por @{u.username}'))
        s.add(row);s.commit();return delivery_json(row,sender,u)

@app.get('/social/notifications')
def delivery_notifications(u=Depends(me)):
    with Session(engine) as s:
        rows=s.exec(select(KDeliveryNotice).where(KDeliveryNotice.user_id==u.id).order_by(KDeliveryNotice.created_at.desc()).limit(100)).all()
        return [{'id':str(n.id),'kind':n.kind,'delivery_id':str(n.delivery_id),'message':n.message,'created_at':n.created_at.isoformat(),'read':n.read} for n in rows]
