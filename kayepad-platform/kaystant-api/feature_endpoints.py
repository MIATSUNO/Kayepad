import json
from app import SQLModel, DBField, UUID, uuid4, datetime, UTC, BaseModel, Field, app, Session, engine, select, KUser, KPost, KSession, KInk, KPurchase, KGroup, KGroupMember, KPet, KBook, KBookPost, KPetTouch, post_json, user_json, me, Depends, HTTPException

# Social graph and editable profiles
class KFollow(SQLModel, table=True):
 __tablename__='kt_follows'
 id:UUID=DBField(default_factory=uuid4,primary_key=True)
 follower_id:UUID=DBField(index=True)
 followed_id:UUID=DBField(index=True)
 created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))

class ProfileEdit(BaseModel):
 username:str|None=Field(default=None,min_length=3,max_length=40)
 bio:str|None=Field(default=None,max_length=280,pattern=r'^[^<>]*$')
 ink_color:str|None=Field(default=None,pattern=r'^#[0-9a-fA-F]{6}$')
 banner_url:str|None=Field(default=None,max_length=500)
 display_name:str|None=Field(default=None,max_length=80)
 show_display_name:bool|None=None
 links:list[str]|None=Field(default=None,max_length=5)
 theme:str|None=None
 instagram_handle:str|None=Field(default=None,max_length=40,pattern=r'^$|^@?[A-Za-z0-9_.]{1,39}$')
 avatar:dict|None=None

@app.get('/users/{username}')
def public_profile(username:str):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.username==username)).first()
  if not u: raise HTTPException(404,'Perfil não encontrado')
  followers=len(s.exec(select(KFollow).where(KFollow.followed_id==u.id)).all())
  following=len(s.exec(select(KFollow).where(KFollow.follower_id==u.id)).all())
  posts=[post_json(s,p) for p in s.exec(select(KPost).where(KPost.user_id==u.id).order_by(KPost.created_at.desc())).all()]
  return {'profile':user_json(u),'followers':followers,'following':following,'posts':posts}

@app.patch('/profile')
def edit_profile(d:ProfileEdit,u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  if d.username is not None and d.username!=x.username:
   if x.username_changed_at and x.username_changed_at.replace(tzinfo=UTC)+__import__('datetime').timedelta(days=7)>datetime.now(UTC): raise HTTPException(429,'Você só poderá alterar o nome de usuário novamente após 7 dias')
   if x.coins<50: raise HTTPException(402,'São necessários 50 coins para alterar o nome de usuário')
   taken=s.exec(select(KUser).where(KUser.username==d.username)).first()
   if taken: raise HTTPException(409,'Este nome de usuário já está em uso')
   x.username=d.username; x.coins-=50; x.username_changed_at=datetime.now(UTC)
  for key in ('bio','ink_color','banner_url','display_name','show_display_name','theme','instagram_handle'):
   value=getattr(d,key)
   if value is not None: setattr(x,key,value)
  if d.links is not None: x.links_json=json.dumps(d.links[:5])
  if d.avatar is not None: x.avatar_json=json.dumps(d.avatar)
  s.add(x);s.commit();s.refresh(x);return user_json(x)

@app.post('/users/{username}/follow')
def follow(username:str,u=Depends(me)):
 with Session(engine) as s:
  target=s.exec(select(KUser).where(KUser.username==username)).first()
  if not target: raise HTTPException(404,'Perfil não encontrado')
  if target.id==u.id: raise HTTPException(400,'Você não pode seguir a si mesmo')
  existing=s.exec(select(KFollow).where(KFollow.follower_id==u.id,KFollow.followed_id==target.id)).first()
  if existing: s.delete(existing); following=False
  else: s.add(KFollow(follower_id=u.id,followed_id=target.id)); following=True
  s.commit(); count=len(s.exec(select(KFollow).where(KFollow.followed_id==target.id)).all())
  return {'following':following,'followers':count}

@app.get('/users/{username}/following')
def following(username:str):
 with Session(engine) as s:
  target=s.exec(select(KUser).where(KUser.username==username)).first()
  if not target: raise HTTPException(404,'Perfil não encontrado')
  ids=s.exec(select(KFollow).where(KFollow.follower_id==target.id)).all()
  return [user_json(s.get(KUser,x.followed_id)) for x in ids]

# --- Ke-Store v2: permanent seal, tickets and temporary special articles ---
class KSealState(SQLModel, table=True):
 __tablename__='kt_seal_states'; user_id:UUID=DBField(primary_key=True); active:bool=True; expires_at:datetime
class KSpecialWallet(SQLModel, table=True):
 __tablename__='kt_special_wallets'; user_id:UUID=DBField(primary_key=True); balance:int=0
class KTicketInventory(SQLModel, table=True):
 __tablename__='kt_ticket_inventory'; user_id:UUID=DBField(primary_key=True); quantity:int=0
class KTicket(SQLModel, table=True):
 __tablename__='kt_tickets'; id:UUID=DBField(default_factory=uuid4,primary_key=True); user_id:UUID=DBField(index=True); post_id:UUID=DBField(index=True); meta:int; progress:int=0; start_ink:int=0; status:str='ativo'; expires_at:datetime; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class KEffect(SQLModel, table=True):
 __tablename__='kt_effects'; id:UUID=DBField(default_factory=uuid4,primary_key=True); user_id:UUID=DBField(index=True); kind:str; post_id:UUID|None=None; value:str=''; expires_at:datetime; created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))
class TicketUseIn(BaseModel): post_id:UUID; meta:int=Field(ge=10,le=40)
class SpecialBuyIn(BaseModel): kind:str; post_id:UUID|None=None; value:str=''

def _expire(s,user_id):
 now=datetime.now(UTC); effects=s.exec(select(KEffect).where(KEffect.user_id==user_id)).all()
 # expired rows stay auditable; they simply are not returned or applied
 tickets=s.exec(select(KTicket).where(KTicket.user_id==user_id,KTicket.status=='ativo')).all()
 for t in tickets:
  if t.expires_at.replace(tzinfo=UTC)<now: t.status='falhou';s.add(t)
def _effect_json(e): return {'id':str(e.id),'kind':e.kind,'post_id':str(e.post_id) if e.post_id else None,'value':e.value,'expires_at':e.expires_at}
def _ticket_json(t): return {'id':str(t.id),'post_id':str(t.post_id),'meta':t.meta,'progress':t.progress,'status':t.status,'expires_at':t.expires_at}

def update_ticket(s,p,user,amount):
 now=datetime.now(UTC); active=s.exec(select(KTicket).where(KTicket.post_id==p.id,KTicket.status=='ativo')).all()
 for t in active:
  if t.expires_at.replace(tzinfo=UTC)<now: t.status='falhou';s.add(t);continue
  t.progress=max(0,min(t.meta,p.ink_total-t.start_ink));
  if t.progress>=t.meta:
   t.status='sucesso'; w=s.get(KSpecialWallet,t.user_id) or KSpecialWallet(user_id=t.user_id,balance=0);w.balance+=t.meta;s.add(w)
  s.add(t)

def ke_wallet(s,u):
 _expire(s,u.id);s.commit(); now=datetime.now(UTC)
 seal=s.get(KSealState,u.id); now=datetime.now(UTC)
 if not seal and owns_item(s,u.id,'selo'):
  seal=KSealState(user_id=u.id,active=True,expires_at=now+timedelta(days=30));s.add(seal);s.commit()
 if seal and seal.expires_at.replace(tzinfo=UTC)<=now: seal.active=False; s.add(seal); s.commit()
 w=s.get(KSpecialWallet,u.id); inv=s.get(KTicketInventory,u.id)
 legacy=s.exec(select(KPurchase).where(KPurchase.user_id==u.id,KPurchase.item=='ticket')).all()
 if legacy and (not inv or inv.quantity<len(legacy)):
  inv=inv or KTicketInventory(user_id=u.id,quantity=0); inv.quantity=max(inv.quantity,len(legacy)); s.add(inv); s.commit()
 return {'coins':u.coins,'special_coins':w.balance if w else 0,'seal':bool(seal and seal.active),'selo_ativo':bool(seal and seal.active),'selo_expira_em':seal.expires_at if seal and seal.active else None,'tickets':inv.quantity if inv else 0,'tickets_active':[_ticket_json(t) for t in s.exec(select(KTicket).where(KTicket.user_id==u.id,KTicket.status=='ativo')).all()],'effects':[_effect_json(e) for e in s.exec(select(KEffect).where(KEffect.user_id==u.id,KEffect.expires_at>now)).all()]}

@app.get('/ke-store/catalog')
def ke_catalog():
 return {'normal':[{'id':'selo','name':'Selo','price':2800,'permanent':True},{'id':'ticket','name':'Ticket','price':600,'permanent':False}],'special':[{'id':'magica','name':'Tinta Mágica','price':5,'days':7},{'id':'autor','name':'Etiqueta de Autor','price':10,'days':30},{'id':'marcador','name':'Marcador de Página','price':3,'days':1},{'id':'broche','name':'Broche Kayepad','price':8,'days':30},{'id':'vela','name':'Vela Nota','price':5,'days':7},{'id':'exlibris','name':'Ex-Libris','price':10,'days':14}]}
@app.get('/me/ke-wallet')
def ke_wallet_me(u=Depends(me)):
 with Session(engine) as s:return ke_wallet(s,s.get(KUser,u.id))
@app.post('/ke-store/buy/{item}')
def ke_buy(item:str,u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id); prices={'selo':2800,'ticket':600}
  if item not in prices: raise HTTPException(400,'Use a carteira de Coins Especiais para este artigo')
  if item=='selo' and owns_item(s,x.id,'selo'): raise HTTPException(409,'Você já possui o Selo')
  if x.coins<prices[item]: raise HTTPException(400,'Coins insuficientes')
  x.coins-=prices[item]
  if item=='selo':
   x.badge='selo';x.verified=True;s.add(KPurchase(user_id=x.id,item='selo',cost=prices[item]));s.add(KSealState(user_id=x.id,active=True,expires_at=datetime.now(UTC)+timedelta(days=30)))
  else:
   inv=s.get(KTicketInventory,x.id) or KTicketInventory(user_id=x.id,quantity=0);inv.quantity+=1;s.add(inv)
  s.add(x);s.commit();return ke_wallet(s,x)
@app.post('/tickets/use')
def use_ticket(d:TicketUseIn,u=Depends(me)):
 with Session(engine) as s:
  inv=s.get(KTicketInventory,u.id);p=s.get(KPost,d.post_id)
  if not inv or inv.quantity<1: raise HTTPException(400,'Você não tem Tickets disponíveis')
  if not p or p.user_id!=u.id: raise HTTPException(403,'Escolha uma publicação sua')
  if s.exec(select(KTicket).where(KTicket.post_id==p.id,KTicket.status=='ativo')).first(): raise HTTPException(409,'Esta publicação já tem um Ticket ativo')
  inv.quantity-=1;t=KTicket(user_id=u.id,post_id=p.id,meta=d.meta,start_ink=p.ink_total,expires_at=datetime.now(UTC)+timedelta(hours=1));s.add(inv);s.add(t);s.commit();return _ticket_json(t)
@app.post('/special/buy')
def special_buy(d:SpecialBuyIn,u=Depends(me)):
 prices={'magica':5,'autor':10,'marcador':3,'broche':8,'vela':5,'exlibris':10};days={'magica':7,'autor':30,'marcador':1,'broche':30,'vela':7,'exlibris':14}
 if d.kind not in prices: raise HTTPException(400,'Artigo especial inválido')
 with Session(engine) as s:
  w=s.get(KSpecialWallet,u.id)
  if not w or w.balance<prices[d.kind]: raise HTTPException(400,'Coins Especiais insuficientes')
  if d.kind in {'autor','marcador','vela'} and (not d.post_id or not (p:=s.get(KPost,d.post_id)) or p.user_id!=u.id): raise HTTPException(403,'Escolha uma publicação sua')
  w.balance-=prices[d.kind];e=KEffect(user_id=u.id,kind=d.kind,post_id=d.post_id,value=d.value,expires_at=datetime.now(UTC)+timedelta(days=days[d.kind]));s.add(w);s.add(e);s.commit();return _effect_json(e)
