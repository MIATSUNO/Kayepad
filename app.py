import os, hashlib, secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from sqlmodel import SQLModel, Field, Session, create_engine, select

DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./kayepad.db')
engine=create_engine(DATABASE_URL, echo=False, connect_args={'check_same_thread':False} if DATABASE_URL.startswith('sqlite') else {})
app=FastAPI(title='Kayepad API', version='1.0.0')
app.add_middleware(CORSMiddleware, allow_origins=os.getenv('CORS_ORIGINS','*').split(','), allow_methods=['*'], allow_headers=['*'])

class User(SQLModel, table=True):
 id: Optional[int]=Field(default=None, primary_key=True); email:str; pseudonym:str; password_hash:str; bio:str=''; avatar_url:str=''; email_verified:bool=False; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc)); badge:str='normal'; banned:bool=False
class Work(SQLModel, table=True):
 id: Optional[int]=Field(default=None, primary_key=True); user_id:int; title:str; excerpt:str=''; cover_url:str=''; chapters:int=0; reads:int=0; votes:int=0; published:bool=True; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class Comment(SQLModel, table=True):
 id: Optional[int]=Field(default=None, primary_key=True); work_id:int; user_id:Optional[int]=None; body:str; created_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))
class Game(SQLModel, table=True):
 id: Optional[int]=Field(default=None, primary_key=True); kind:str; prompt:str; answer:str; cover_url:str=''; active:bool=True

@app.on_event('startup')
def startup(): SQLModel.metadata.create_all(engine)

def token_for(user): return hashlib.sha256(f'{user.id}:{user.email}:{os.getenv("JWT_SECRET","change-me")}'.encode()).hexdigest()
def current_user(authorization:Optional[str]=Header(None)):
 if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Autenticação necessária')
 value=authorization[7:]
 with Session(engine) as s:
  for u in s.exec(select(User)).all():
   if secrets.compare_digest(token_for(u),value):
    if u.banned: raise HTTPException(403,'Conta banida')
    return u
 raise HTTPException(401,'Sessão inválida')
def admin_key(x_admin_key:Optional[str]=Header(None)):
 key=os.getenv('ADMIN_API_KEY')
 if not key or not x_admin_key or not secrets.compare_digest(key,x_admin_key): raise HTTPException(403,'Acesso administrativo negado')
 return True
class Signup(BaseModel): email:EmailStr; pseudonym:str; password:str
class CommentIn(BaseModel): body:str
class BadgeIn(BaseModel): badge:str

@app.get('/health')
def health(): return {'status':'ok','service':'kayepad-api','time':datetime.now(timezone.utc)}
@app.post('/auth/signup')
def signup(data:Signup):
 with Session(engine) as s:
  if s.exec(select(User).where(User.email==data.email)).first(): raise HTTPException(409,'E-mail já cadastrado')
  u=User(email=data.email,pseudonym=data.pseudonym,password_hash=hashlib.sha256(data.password.encode()).hexdigest()); s.add(u); s.commit(); s.refresh(u)
  return {'user':{'id':u.id,'pseudonym':u.pseudonym,'badge':u.badge},'token':token_for(u)}
@app.get('/me')
def me(u=Depends(current_user)): return u
@app.get('/works')
def works(limit:int=Query(20,le=100), offset:int=0):
 with Session(engine) as s:
  rows=s.exec(select(Work,User).join(User,User.id==Work.user_id).where(Work.published).offset(offset).limit(limit)).all()
  return [{'id':w.id,'title':w.title,'excerpt':w.excerpt,'cover_url':w.cover_url,'chapters':w.chapters,'reads':w.reads,'votes':w.votes,'author':a.pseudonym,'badge':a.badge} for w,a in rows]
@app.post('/works/{work_id}/read')
def read(work_id:int):
 with Session(engine) as s:
  w=s.get(Work,work_id)
  if not w: raise HTTPException(404,'Obra não encontrada')
  w.reads+=1; s.add(w); s.commit(); return {'reads':w.reads}
@app.post('/works/{work_id}/vote')
def vote(work_id:int):
 with Session(engine) as s:
  w=s.get(Work,work_id)
  if not w: raise HTTPException(404,'Obra não encontrada')
  w.votes+=1; s.add(w); s.commit(); return {'votes':w.votes}
@app.get('/works/{work_id}/comments')
def comments(work_id:int):
 with Session(engine) as s: return s.exec(select(Comment).where(Comment.work_id==work_id).order_by(Comment.created_at.desc())).all()
@app.post('/works/{work_id}/comments')
def add_comment(work_id:int,data:CommentIn,u=Depends(current_user)):
 with Session(engine) as s:
  c=Comment(work_id=work_id,user_id=u.id,body=data.body[:2000]); s.add(c); s.commit(); s.refresh(c); return c
@app.get('/reels')
def reels(): return works(30,0)
@app.get('/games')
def games(kind:Optional[str]=None):
 with Session(engine) as s: return s.exec(select(Game).where(Game.active, Game.kind==kind if kind else True)).all()
@app.post('/admin/users/{user_id}/badge')
def set_badge(user_id:int,data:BadgeIn,_=Depends(admin_key)):
 if data.badge not in {'normal','support','ambassador','partner','verified'}: raise HTTPException(400,'Selo inválido')
 with Session(engine) as s:
  u=s.get(User,user_id)
  if not u: raise HTTPException(404,'Usuário não encontrado')
  u.badge=data.badge; s.add(u); s.commit(); return {'id':u.id,'badge':u.badge}
@app.post('/admin/users/{user_id}/ban')
def ban(user_id:int,_=Depends(admin_key)):
 with Session(engine) as s:
  u=s.get(User,user_id)
  if not u: raise HTTPException(404,'Usuário não encontrado')
  u.banned=True; s.add(u); s.commit(); return {'id':u.id,'banned':True}
@app.get('/admin/users')
def admin_users(_=Depends(admin_key)):
 with Session(engine) as s: return s.exec(select(User).order_by(User.created_at.desc())).all()
