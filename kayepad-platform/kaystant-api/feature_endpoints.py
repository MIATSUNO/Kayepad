import json
from pydantic import field_validator
from sqlalchemy import select as sa_select
from sqlalchemy.exc import IntegrityError
from app import SQLModel, DBField, UUID, uuid4, datetime, timedelta, UTC, BaseModel, Field, app, Session, engine, select, KUser, KPost, KSession, KInk, KPurchase, KGroup, KGroupMember, KPet, KBook, KBookPost, KPetTouch, post_json, user_json, me, Depends, HTTPException, is_safe_http_url

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

 @field_validator('links')
 @classmethod
 def validate_links(cls,value):
  if value is None: return value
  clean=[]
  for item in value:
   link=item.strip()
   if not link or len(link)>500 or not is_safe_http_url(link): raise ValueError('Os links precisam usar http ou https e ter um endereço válido')
   clean.append(link)
  return clean

 @field_validator('banner_url')
 @classmethod
 def validate_banner_url(cls,value):
  if value is not None and not is_safe_http_url(value): raise ValueError('Use um endereço http ou https válido')
  return value

 @field_validator('avatar')
 @classmethod
 def validate_avatar(cls,value):
  if value is None: return value
  if not isinstance(value,dict): raise ValueError('Ícone inválido')
  url=value.get('url','')
  if not isinstance(url,str) or len(url)>500 or (url and not is_safe_http_url(url)): raise ValueError('Use um endereço http ou https válido para o ícone')
  return {'url':url.strip()}

@app.get('/users/{username}')
def public_profile(username:str):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.username==username)).first()
  if not u: raise HTTPException(404,'Perfil não encontrado')
  followers=len(s.exec(select(KFollow).where(KFollow.followed_id==u.id)).all())
  following=len(s.exec(select(KFollow).where(KFollow.follower_id==u.id)).all())
  posts=[post_json(s,p) for p in s.exec(select(KPost).where(KPost.user_id==u.id).order_by(KPost.created_at.desc())).all()]
  st=active_seal(s,u.id) if 'active_seal' in globals() else None; sp=s.get(KSealProfile,u.id) if 'KSealProfile' in globals() else None
  profile=user_json(u);profile.update({'selo_ativo':bool(st),'selo_expira_em':st.expires_at if st else None,'seal':{'gif_url':sp.gif_url if sp else '','music_url':sp.music_url if sp else '','border_style':sp.border_style if sp else 'holografica'}})
  return {'profile':profile,'followers':followers,'following':following,'posts':posts}

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

@app.get('/users/{username}/follow-status')
def follow_status(username:str,u=Depends(me)):
 with Session(engine) as s:
  target=s.exec(select(KUser).where(KUser.username==username)).first()
  if not target: raise HTTPException(404,'Perfil não encontrado')
  return {'following':bool(s.exec(select(KFollow).where(KFollow.follower_id==u.id,KFollow.followed_id==target.id)).first())}
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
 if seal and seal.expires_at.replace(tzinfo=UTC)<=now: seal.active=False; s.add(seal); s.commit()
 w=s.get(KSpecialWallet,u.id); inv=s.get(KTicketInventory,u.id)
 legacy=s.exec(select(KPurchase).where(KPurchase.user_id==u.id,KPurchase.item=='ticket')).all()
 if legacy and (not inv or inv.quantity<len(legacy)):
  inv=inv or KTicketInventory(user_id=u.id,quantity=0); inv.quantity=max(inv.quantity,len(legacy)); s.add(inv); s.commit()
 return {'coins':u.coins,'special_coins':w.balance if w else 0,'seal':bool(seal and seal.active),'selo_ativo':bool(seal and seal.active),'selo_expira_em':seal.expires_at if seal and seal.active else None,'tickets':inv.quantity if inv else 0,'tickets_active':[_ticket_json(t) for t in s.exec(select(KTicket).where(KTicket.user_id==u.id,KTicket.status=='ativo')).all()],'effects':[_effect_json(e) for e in s.exec(select(KEffect).where(KEffect.user_id==u.id,KEffect.expires_at>now)).all()]}

@app.get('/ke-store/catalog')
def ke_catalog():
 return {'normal':[{'id':'selo','name':'Selo','price':2800,'days':30},{'id':'ticket','name':'Ticket','price':600},{'id':'ink','name':'Cargas de Tinta','price':100,'quantity':50}],'special':[{'id':'cambio','name':'Câmbio','price':60,'days':7},{'id':'exlibris','name':'Ex-Libris','price':120,'days':7}]}
@app.get('/me/ke-wallet')
def ke_wallet_me(u=Depends(me)):
 with Session(engine) as s:return ke_wallet(s,s.get(KUser,u.id))
@app.post('/ke-store/buy/{item}')
def ke_buy(item:str,u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id); prices={'selo':2800,'ticket':600}
  if item not in prices: raise HTTPException(400,'Use a carteira de Coins Especiais para este artigo')
  seal=s.get(KSealState,x.id)
  if item=='selo' and seal and seal.active and seal.expires_at.replace(tzinfo=UTC)>datetime.now(UTC):
   # compra de renovação: mantém o benefício atual e acrescenta 30 dias
   pass
  if x.coins<prices[item]: raise HTTPException(400,'Coins insuficientes')
  x.coins-=prices[item]
  if item=='selo':
   x.badge='selo';x.verified=True;s.add(KPurchase(user_id=x.id,item='selo',cost=prices[item]));base=seal.expires_at if seal and seal.active and seal.expires_at.replace(tzinfo=UTC)>datetime.now(UTC) else datetime.now(UTC);seal=seal or KSealState(user_id=x.id,active=True,expires_at=base+timedelta(days=30));seal.active=True;seal.expires_at=base+timedelta(days=30);s.add(seal)
  else:
   inv=s.get(KTicketInventory,x.id) or KTicketInventory(user_id=x.id,quantity=0);inv.quantity+=1;s.add(inv)
  s.add(x);s.commit();return ke_wallet(s,x)
@app.post('/tickets/use')
def use_ticket(d:TicketUseIn,u=Depends(me)):
 try:
  with Session(engine) as s:
   inv=s.get(KTicketInventory,u.id);p=s.get(KPost,d.post_id)
   if not inv:
    legacy=s.exec(select(KPurchase).where(KPurchase.user_id==u.id,KPurchase.item=='ticket')).all()
    if legacy: inv=KTicketInventory(user_id=u.id,quantity=len(legacy));s.add(inv);s.flush()
   if not inv or inv.quantity<1: raise HTTPException(400,'Você não tem Tickets disponíveis')
   if not p or p.user_id!=u.id: raise HTTPException(403,'Escolha uma publicação sua')
   if s.exec(select(KTicket).where(KTicket.post_id==p.id,KTicket.status=='ativo')).first(): raise HTTPException(409,'Esta publicação já tem um Ticket ativo')
   inv.quantity-=1;t=KTicket(user_id=u.id,post_id=p.id,meta=d.meta,start_ink=p.ink_total,expires_at=datetime.now(UTC)+timedelta(hours=1));s.add(inv);s.add(t);s.commit();return _ticket_json(t)
 except HTTPException: raise
 except Exception as e: raise HTTPException(500,'Ticket não pôde ser ativado: '+str(e)[:240])
class KExchangeReceipt(SQLModel,table=True):
 __tablename__='kt_exchange_receipts'
 id:UUID=DBField(primary_key=True)
 user_id:UUID=DBField(index=True)
 direction:str
 amount:int
 coins_after:int
 special_after:int
 created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))

class ExchangeIn(BaseModel):
 direction:str
 amount:int=Field(ge=1,le=1000000,strict=True)
 request_id:UUID

def _lock_user(s,user_id):
 return s.exec(select(KUser).where(KUser.id==user_id).with_for_update()).one()
def _lock_wallet(s,user_id):
 return s.exec(select(KSpecialWallet).where(KSpecialWallet.user_id==user_id).with_for_update()).first()
def _active_effect(s,user_id,kind):
 return s.exec(select(KEffect).where(KEffect.user_id==user_id,KEffect.kind==kind,KEffect.expires_at>datetime.now(UTC)).order_by(KEffect.expires_at.desc())).first()

@app.post('/special/buy')
def special_buy(d:SpecialBuyIn,u=Depends(me)):
 prices={'cambio':60,'exlibris':120}
 if d.kind not in prices: raise HTTPException(400,'Artigo especial inválido')
 with Session(engine) as s:
  _lock_user(s,u.id)
  w=_lock_wallet(s,u.id)
  if _active_effect(s,u.id,d.kind): raise HTTPException(409,'Este artigo já está ativo no seu perfil')
  if not w or w.balance<prices[d.kind]: raise HTTPException(400,'Coins Especiais insuficientes')
  w.balance-=prices[d.kind]
  e=KEffect(user_id=u.id,kind=d.kind,post_id=None,value='',expires_at=datetime.now(UTC)+timedelta(days=7))
  s.add(w);s.add(e);s.commit();s.refresh(e)
  return _effect_json(e)

@app.post('/special/exchange')
def convert_currency(d:ExchangeIn,u=Depends(me)):
 if d.direction not in {'coins_to_special','special_to_coins'}: raise HTTPException(422,'Escolha o sentido do câmbio')
 if d.direction=='special_to_coins' and d.amount%5: raise HTTPException(422,'Use um múltiplo de 5 Coins Especiais')
 with Session(engine) as s:
  x=_lock_user(s,u.id)
  receipt=s.get(KExchangeReceipt,d.request_id)
  if receipt:
   if receipt.user_id!=u.id or receipt.direction!=d.direction or receipt.amount!=d.amount: raise HTTPException(409,'Operação já utilizada')
   return {'coins':receipt.coins_after,'special_coins':receipt.special_after,'replayed':True}
  if not _active_effect(s,u.id,'cambio'): raise HTTPException(403,'O Câmbio não está ativo')
  w=_lock_wallet(s,u.id)
  if not w: w=KSpecialWallet(user_id=u.id,balance=0);s.add(w)
  if d.direction=='coins_to_special':
   if x.coins<d.amount: raise HTTPException(400,'Coins insuficientes')
   if w.balance+d.amount*5>2147483647: raise HTTPException(400,'O saldo excede o limite permitido')
   x.coins-=d.amount;w.balance+=d.amount*5
  else:
   if w.balance<d.amount: raise HTTPException(400,'Coins Especiais insuficientes')
   if x.coins+d.amount//5>2147483647: raise HTTPException(400,'O saldo excede o limite permitido')
   w.balance-=d.amount;x.coins+=d.amount//5
  s.add(x);s.add(w);s.add(KExchangeReceipt(id=d.request_id,user_id=u.id,direction=d.direction,amount=d.amount,coins_after=x.coins,special_after=w.balance))
  try:s.commit()
  except IntegrityError:s.rollback();raise HTTPException(409,'Operação já registrada; atualize seus saldos')
  return {'coins':x.coins,'special_coins':w.balance,'replayed':False}

class KSealProfile(SQLModel, table=True):
 __tablename__='kt_seal_profiles'; user_id:UUID=DBField(primary_key=True); gif_url:str=''; music_url:str=''; border_style:str='holografica'
class SealProfileIn(BaseModel): gif_url:str=Field(default='',max_length=500); music_url:str=Field(default='',max_length=500); border_style:str=Field(default='holografica',max_length=30)
def active_seal(s,user_id):
 x=s.get(KSealState,user_id); now=datetime.now(UTC)
 if not x or not x.active or x.expires_at.replace(tzinfo=UTC)<=now:
  if x and x.active: x.active=False;s.add(x);s.commit()
  return None
 return x
@app.get('/users/{username}/seal')
def public_seal(username:str):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.username==username)).first()
  if not u: raise HTTPException(404,'Perfil não encontrado')
  seal=active_seal(s,u.id); p=s.get(KSealProfile,u.id)
  return {'active':bool(seal),'expires_at':seal.expires_at if seal else None,'gif_url':p.gif_url if p else '','music_url':p.music_url if p else '','border_style':p.border_style if p else 'holografica'}
@app.patch('/me/seal')
def edit_seal(d:SealProfileIn,u=Depends(me)):
 with Session(engine) as s:
  if not active_seal(s,u.id): raise HTTPException(403,'Compre o Selo para desbloquear esta personalização')
  if not _active_effect(s,u.id,'exlibris') and (d.gif_url or d.music_url): raise HTTPException(403,'Ative o Ex-Libris para editar banner e música')
  p=s.get(KSealProfile,u.id) or KSealProfile(user_id=u.id);p.gif_url=d.gif_url;p.music_url=d.music_url;p.border_style=d.border_style;s.add(p);s.commit();return {'active':True,'gif_url':p.gif_url,'music_url':p.music_url,'border_style':p.border_style}

class ExLibrisIn(BaseModel):
 gif_url:str=Field(default='',max_length=500)
 music_url:str=Field(default='',max_length=500)
 @field_validator('gif_url','music_url')
 @classmethod
 def validate_media(cls,value):
  value=value.strip()
  if value and (not is_safe_http_url(value) or not value.lower().startswith('https://')): raise ValueError('Use um endereço HTTPS válido')
  return value

@app.get('/users/{username}/exlibris')
def public_exlibris(username:str):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.username==username)).first()
  if not u: raise HTTPException(404,'Perfil não encontrado')
  effect=_active_effect(s,u.id,'exlibris');p=s.get(KSealProfile,u.id)
  return {'active':bool(effect),'expires_at':effect.expires_at if effect else None,'gif_url':p.gif_url if effect and p else '', 'music_url':p.music_url if effect and p else ''}

@app.get('/me/exlibris')
def get_my_exlibris(u=Depends(me)):
 return public_exlibris(u.username)

@app.patch('/me/exlibris')
def edit_exlibris(d:ExLibrisIn,u=Depends(me)):
 with Session(engine) as s:
  _lock_user(s,u.id)
  if not _active_effect(s,u.id,'exlibris'): raise HTTPException(403,'Ative o Ex-Libris para editar o banner e a música')
  p=s.get(KSealProfile,u.id) or KSealProfile(user_id=u.id)
  p.gif_url=d.gif_url;p.music_url=d.music_url;s.add(p);s.commit()
  return {'active':True,'gif_url':p.gif_url,'music_url':p.music_url}

@app.post('/ink-shop/buy')
def buy_ink(u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  if x.coins<100: raise HTTPException(400,'São necessários 100 Coins para comprar 50 Tintas')
  x.coins-=100;x.ink+=50;s.add(x);s.commit();return {'coins':x.coins,'ink':x.ink,'purchased':50}
