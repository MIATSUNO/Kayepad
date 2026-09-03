import os, secrets, hashlib, re, json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, Depends, HTTPException, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlmodel import SQLModel, Field as DBField, Session, create_engine, select
from sqlalchemy import text
import bcrypt

UTC=timezone.utc
DATABASE_URL=os.getenv('DATABASE_URL','sqlite:///./kaystant.db')
if DATABASE_URL.startswith('postgres://'): DATABASE_URL='postgresql+psycopg://'+DATABASE_URL[11:]
elif DATABASE_URL.startswith('postgresql://'): DATABASE_URL='postgresql+psycopg://'+DATABASE_URL[13:]
sqlite=DATABASE_URL.startswith('sqlite'); engine=create_engine(DATABASE_URL,pool_pre_ping=True,connect_args={'check_same_thread':False} if sqlite else {'prepare_threshold':None})
SECRET=os.getenv('JWT_SECRET','kaystant-dev-only-change-me')
app=FastAPI(title='Kaystant API',version='0.1.0')
origins=[x.strip() for x in os.getenv('CORS_ORIGINS','https://kayepad.neocities.org,http://localhost:3000').split(',') if x.strip()]
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_methods=['GET','POST','PATCH','DELETE','OPTIONS'],allow_headers=['Authorization','Content-Type'])

class KUser(SQLModel,table=True):
 __tablename__='kt_users'; id:UUID=DBField(default_factory=uuid4,primary_key=True); email:str=DBField(unique=True,index=True); username:str=DBField(unique=True,index=True); password_hash:str; bio:str=''; ink_color:str='#5367d8'; coins:int=0; ink:int=18; badge:str='normal'; banner_url:str=''; display_name:str=''; show_display_name:bool=True; links_json:str='[]'; theme:str='paper'; verified:bool=False; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KSession(SQLModel,table=True):
 __tablename__='kt_sessions'; id:UUID=DBField(default_factory=uuid4,primary_key=True); user_id:UUID=DBField(index=True); token_hash:str=DBField(unique=True,index=True); expires_at:datetime; revoked:bool=False
class KPost(SQLModel,table=True):
 __tablename__='kt_posts'; id:UUID=DBField(default_factory=uuid4,primary_key=True); user_id:UUID=DBField(index=True); title:str; category:str; body:str; ink_total:int=0; ink_goal:int=100; coins_awarded:int|None=None; redeemed_at:datetime|None=None; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KInk(SQLModel,table=True):
 __tablename__='kt_inks'; id:UUID=DBField(default_factory=uuid4,primary_key=True); post_id:UUID=DBField(index=True); user_id:UUID=DBField(index=True); amount:int=1; color:str; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KPurchase(SQLModel,table=True):
 __tablename__='kt_purchases'; id:UUID=DBField(default_factory=uuid4,primary_key=True); user_id:UUID=DBField(index=True); item:str; cost:int; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))

class Signup(BaseModel): email:str; username:str=Field(min_length=3,max_length=40); password:str=Field(min_length=8,max_length=128); full_name:str=Field(default='',max_length=100)
ALLOWED_EMAIL_DOMAINS={'gmail.com','googlemail.com','hotmail.com','outlook.com','kaystant.org'}
def allowed_email(email):
 return email.lower().rsplit('@',1)[-1] in ALLOWED_EMAIL_DOMAINS
class Login(BaseModel): email:str; password:str
class PostIn(BaseModel): title:str=Field(min_length=1,max_length=140); category:str; body:str=Field(min_length=1,max_length=30000)
class ProfileIn(BaseModel): bio:str|None=None; ink_color:str|None=None; banner_url:str|None=None
class InkIn(BaseModel): amount:int=Field(default=1,ge=1,le=10)

@app.on_event('startup')
def startup():
 if not sqlite:
  with engine.begin() as c:
   c.execute(text("ALTER TABLE kt_users ADD COLUMN IF NOT EXISTS display_name TEXT DEFAULT ''")); c.execute(text("ALTER TABLE kt_users ADD COLUMN IF NOT EXISTS show_display_name BOOLEAN DEFAULT TRUE")); c.execute(text("ALTER TABLE kt_users ADD COLUMN IF NOT EXISTS links_json TEXT DEFAULT '[]'")); c.execute(text("ALTER TABLE kt_users ADD COLUMN IF NOT EXISTS theme TEXT DEFAULT 'paper'"))
 SQLModel.metadata.create_all(engine)
@app.get('/health')
def health(): return {'status':'ok','service':'kaystant-api'}
def pw(v): return bcrypt.hashpw(v.encode(),bcrypt.gensalt()).decode()
def issue(u):
 raw=secrets.token_urlsafe(48); h=hashlib.sha256(raw.encode()).hexdigest()
 with Session(engine) as s: s.add(KSession(user_id=u.id,token_hash=h,expires_at=datetime.now(UTC)+timedelta(days=30))); s.commit()
 return raw
def me(authorization: str|None=Header(None)):
 if not authorization or not authorization.startswith('Bearer '): raise HTTPException(401,'Faça login para continuar')
 h=hashlib.sha256(authorization[7:].encode()).hexdigest()
 with Session(engine) as s:
  ss=s.exec(select(KSession).where(KSession.token_hash==h,KSession.revoked==False)).first(); u=s.get(KUser,ss.user_id) if ss else None
  if not ss or not u or ss.expires_at.replace(tzinfo=UTC)<datetime.now(UTC): raise HTTPException(401,'Sessão expirada')
  return u
def user_json(u): return {'id':str(u.id),'username':u.username,'bio':u.bio,'ink_color':u.ink_color,'coins':u.coins,'ink':u.ink,'badge':u.badge,'banner_url':u.banner_url,'display_name':u.display_name,'show_display_name':u.show_display_name,'links':json.loads(u.links_json or '[]'),'theme':u.theme,'verified':u.verified}
def post_json(s,p):
 u=s.get(KUser,p.user_id); return {'id':str(p.id),'title':p.title,'category':p.category,'body':p.body,'ink_total':p.ink_total,'ink_goal':p.ink_goal,'fill':min(100,round(p.ink_total/p.ink_goal*100)),'coins_awarded':p.coins_awarded,'redeemed':bool(p.redeemed_at),'author':user_json(u),'created_at':p.created_at}
@app.post('/auth/signup')
def signup(d:Signup):
 if not allowed_email(d.email): raise HTTPException(422,'Use Gmail, Hotmail, Outlook ou Kaystant Mail')
 if not re.fullmatch(r'[A-Za-z0-9_.-]{3,40}',d.username): raise HTTPException(422,'Nome de usuário inválido')
 with Session(engine) as s:
  if s.exec(select(KUser).where((KUser.email==d.email.lower())|(KUser.username==d.username))).first(): raise HTTPException(409,'E-mail ou nome de usuário já usado')
  u=KUser(email=d.email.lower(),username=d.username,display_name=d.full_name,password_hash=pw(d.password),coins=650); s.add(u); s.commit(); s.refresh(u); return {'user':user_json(u),'token':issue(u)}
@app.post('/auth/login')
def login(d:Login):
 if not allowed_email(d.email): raise HTTPException(422,'Domínio de e-mail não permitido')
 with Session(engine) as s: u=s.exec(select(KUser).where(KUser.email==d.email.lower())).first()
 if not u or not bcrypt.checkpw(d.password.encode(),u.password_hash.encode()): raise HTTPException(401,'Credenciais inválidas')
 return {'user':user_json(u),'token':issue(u)}
@app.post('/auth/logout')
def logout(authorization: str|None=Header(None)):
 if authorization and authorization.startswith('Bearer '):
  h=hashlib.sha256(authorization[7:].encode()).hexdigest()
  with Session(engine) as s:
   ss=s.exec(select(KSession).where(KSession.token_hash==h)).first()
   if ss: ss.revoked=True; s.add(ss); s.commit()
 return {'ok':True}
@app.get('/me')
def get_me(u=Depends(me)): return user_json(u)
@app.patch('/me')
def patch_me(d:ProfileIn,u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  for key in ('bio','ink_color','banner_url'):
   val=getattr(d,key)
   if val is not None: setattr(x,key,val)
  s.add(x); s.commit(); s.refresh(x); return user_json(x)
@app.get('/feed')
def feed(limit:int=30):
 with Session(engine) as s: return [post_json(s,p) for p in s.exec(select(KPost).order_by(KPost.created_at.desc()).limit(min(limit,100))).all()]
@app.post('/posts')
def create_post(d:PostIn,u=Depends(me)):
 if d.category not in {'poesia','artigo_cientifico','estudo_pesquisa'}: raise HTTPException(422,'Categoria não permitida')
 with Session(engine) as s: p=KPost(user_id=u.id,title=d.title,category=d.category,body=d.body);s.add(p);s.commit();s.refresh(p);return post_json(s,p)
@app.post('/posts/{post_id}/ink')
def add_ink(post_id:UUID,d:InkIn,u=Depends(me)):
 with Session(engine) as s:
  p=s.get(KPost,post_id)
  if not p: raise HTTPException(404,'Publicação não encontrada')
  if p.user_id==u.id: raise HTTPException(400,'A própria publicação não recebe sua tinta')
  existing=s.exec(select(KInk).where(KInk.post_id==post_id,KInk.user_id==u.id)).first()
  if existing: raise HTTPException(409,'Você já deixou tinta nesta publicação')
  x=s.get(KUser,u.id)
  if x.ink<d.amount: raise HTTPException(400,'Você não tem tinta suficiente')
  x.ink-=d.amount;p.ink_total+=d.amount;s.add(KInk(post_id=post_id,user_id=u.id,amount=d.amount,color=x.ink_color));s.commit();return post_json(s,p)
@app.post('/posts/{post_id}/redeem')
def redeem(post_id:UUID,u=Depends(me)):
 with Session(engine) as s:
  p=s.get(KPost,post_id)
  if not p or p.user_id!=u.id: raise HTTPException(404,'Publicação não encontrada')
  if p.ink_total<p.ink_goal: raise HTTPException(400,'O frasco ainda não encheu')
  if p.redeemed_at: raise HTTPException(409,'Coins já resgatados nesta publicação')
  amount=secrets.randbelow(16);p.coins_awarded=amount;p.redeemed_at=datetime.now(UTC);x=s.get(KUser,u.id);x.coins+=amount;s.commit();return {'coins':amount,'user':user_json(x)}
@app.post('/shop/{item}')
def shop(item:str,u=Depends(me)):
 costs={'selo':1200,'regua':1000,'caneta':2900}
 if item not in costs: raise HTTPException(404,'Item não encontrado')
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  if x.coins<costs[item]: raise HTTPException(400,'Coins insuficientes')
  x.coins-=costs[item];s.add(KPurchase(user_id=x.id,item=item,cost=costs[item]))
  if item=='selo': x.badge='selo'
  if item=='caneta': x.badge='verificado';x.verified=True
  s.commit();return {'item':item,'user':user_json(x)}

# --- Kaystant second layer: pets, groups, books and author highlights ---
class KGroup(SQLModel, table=True):
 __tablename__='kt_groups'; id:UUID=DBField(default_factory=uuid4,primary_key=True); owner_id:UUID=DBField(index=True); name:str; hashtag:str=DBField(unique=True); rules:str=''; image_url:str=''; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KGroupMember(SQLModel, table=True):
 __tablename__='kt_group_members'; group_id:UUID=DBField(primary_key=True); user_id:UUID=DBField(primary_key=True,index=True); joined_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KBook(SQLModel, table=True):
 __tablename__='kt_books'; id:UUID=DBField(default_factory=uuid4,primary_key=True); owner_id:UUID=DBField(index=True); title:str; description:str=''; cover_url:str=''; published:bool=True; featured_until:datetime|None=None; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KBookPost(SQLModel, table=True):
 __tablename__='kt_book_posts'; book_id:UUID=DBField(primary_key=True); post_id:UUID=DBField(primary_key=True); position:int=0
class GroupIn(BaseModel): name:str=Field(min_length=1,max_length=80); hashtag:str=Field(min_length=2,max_length=40); rules:str=Field(default='',max_length=2000); image_url:str=Field(default='',max_length=500)
def owns_item(s,user_id,item): return s.exec(select(KPurchase).where(KPurchase.user_id==user_id,KPurchase.item==item)).first() is not None
def group_json(s,g):
 owner=s.get(KUser,g.owner_id); members=s.exec(select(KGroupMember).where(KGroupMember.group_id==g.id)).all(); return {'id':str(g.id),'name':g.name,'hashtag':g.hashtag,'rules':g.rules,'image_url':g.image_url,'owner':user_json(owner),'members':len(members),'max_members':10}
def book_json(s,b):
 owner=s.get(KUser,b.owner_id); links=s.exec(select(KBookPost).where(KBookPost.book_id==b.id)).all(); return {'id':str(b.id),'title':b.title,'description':b.description,'cover_url':b.cover_url,'owner':user_json(owner),'post_ids':[str(x.post_id) for x in links],'featured_until':b.featured_until}
@app.post('/groups')
def create_group(d:GroupIn,u=Depends(me)):
 with Session(engine) as s:
  if not owns_item(s,u.id,'regua'): raise HTTPException(402,'Compre uma Régua para criar um grupo')
  if s.exec(select(KGroup).where(KGroup.owner_id==u.id)).all(): raise HTTPException(409,'Você já possui um grupo')
  g=KGroup(owner_id=u.id,name=d.name,hashtag=d.hashtag if d.hashtag.startswith('#') else '#'+d.hashtag,rules=d.rules,image_url=d.image_url);s.add(g);s.flush();s.add(KGroupMember(group_id=g.id,user_id=u.id));s.commit();s.refresh(g);return group_json(s,g)
@app.get('/groups')
def groups(limit:int=30):
 with Session(engine) as s:return [group_json(s,g) for g in s.exec(select(KGroup).order_by(KGroup.created_at.desc()).limit(min(limit,100))).all()]
@app.post('/groups/{group_id}/join')
def join_group(group_id:UUID,u=Depends(me)):
 with Session(engine) as s:
  g=s.get(KGroup,group_id)
  if not g: raise HTTPException(404,'Grupo não encontrado')
  members=s.exec(select(KGroupMember).where(KGroupMember.group_id==group_id)).all()
  if len(members)>=10: raise HTTPException(409,'Este grupo já chegou a 10 usuários')
  if any(x.user_id==u.id for x in members): return group_json(s,g)
  s.add(KGroupMember(group_id=group_id,user_id=u.id));s.commit();return group_json(s,g)
@app.post('/books')
def create_book(d:BookIn,u=Depends(me)):
 with Session(engine) as s:
  if not owns_item(s,u.id,'caneta'): raise HTTPException(402,'Compre uma Caneta para publicar um livro')
  posts=[s.get(KPost,pid) for pid in d.post_ids]
  if any(not p or p.user_id!=u.id for p in posts): raise HTTPException(403,'O livro só pode conter seus próprios artigos')
  b=KBook(owner_id=u.id,title=d.title,description=d.description,cover_url=d.cover_url);s.add(b);s.flush()
  for i,p in enumerate(posts):s.add(KBookPost(book_id=b.id,post_id=p.id,position=i))
  b.featured_until=datetime.now(UTC)+timedelta(days=3);x=s.get(KUser,u.id);x.verified=True;x.badge='verificado';s.commit();s.refresh(b);return book_json(s,b)
@app.get('/books')
def books():
 with Session(engine) as s:return [book_json(s,b) for b in s.exec(select(KBook).order_by(KBook.created_at.desc())).all()]
@app.get('/highlights')
def highlights():
 with Session(engine) as s:
  now=datetime.now(UTC);return [book_json(s,b) for b in s.exec(select(KBook).where(KBook.featured_until>now).order_by(KBook.featured_until.desc())).all()]

from feature_endpoints import *
from account_endpoints import *
from auth_endpoints import *
