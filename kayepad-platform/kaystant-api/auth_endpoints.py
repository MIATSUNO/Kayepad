import os, httpx, secrets, hashlib
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from pydantic import BaseModel, Field
from app import app, Session, engine, select, KUser, pw
class RecoverIn(BaseModel): email:str=Field(pattern=r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
class KaystantRecoverIn(BaseModel): full_name:str=Field(min_length=1,max_length=100); email:str=Field(pattern=r'^[^@\s]+@kaystant\.org$'); username:str=Field(min_length=3,max_length=40)
class ResetIn(BaseModel): token:str=min_length(32); password:str=Field(min_length=8,max_length=128)
@app.post('/auth/recover')
def recover(d:RecoverIn):
 base=os.getenv('SUPABASE_URL','').rstrip('/'); key=os.getenv('SUPABASE_ANON_KEY','')
 if not base or not key: raise HTTPException(503,'Recuperação temporariamente indisponível')
 try:r=httpx.post(base+'/auth/v1/recover',headers={'apikey':key,'Content-Type':'application/json'},json={'email':str(d.email),'redirect_to':os.getenv('PASSWORD_RESET_REDIRECT','https://kayepad.neocities.org/test/')},timeout=15)
 except Exception: raise HTTPException(503,'Não foi possível enviar o e-mail agora')
 if r.status_code>=400: raise HTTPException(400,'Não foi possível enviar o e-mail para este endereço')
 return {'sent':True}
@app.post('/auth/recover-kaystant')
def recover_kaystant(d:KaystantRecoverIn):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.email==d.email.lower(),KUser.username==d.username, KUser.display_name==d.full_name)).first()
  if not u: raise HTTPException(400,'Os dados não correspondem a uma conta Kaystant')
  raw=secrets.token_urlsafe(48); h=hashlib.sha256(raw.encode()).hexdigest(); s.execute(__import__('sqlalchemy').text("UPDATE kt_password_resets SET used=TRUE WHERE user_id=:uid AND used=FALSE"),{'uid':str(u.id)})
  s.execute(__import__('sqlalchemy').text("INSERT INTO kt_password_resets (id,user_id,token_hash,expires_at,used) VALUES (:id,:uid,:h,:exp,FALSE)"),{'id':str(secrets.token_hex(16)),'uid':str(u.id),'h':h,'exp':datetime.now(timezone.utc)+timedelta(minutes=15)}); s.commit()
 return {'verified':True,'reset_token':raw}
@app.post('/auth/reset-password')
def reset_password(d:ResetIn):
 h=hashlib.sha256(d.token.encode()).hexdigest()
 with Session(engine) as s:
  row=s.execute(__import__('sqlalchemy').text("SELECT id,user_id,expires_at,used FROM kt_password_resets WHERE token_hash=:h"),{'h':h}).mappings().first()
  if not row or row['used'] or row['expires_at'].replace(tzinfo=timezone.utc)<datetime.now(timezone.utc): raise HTTPException(400,'Código de recuperação inválido ou expirado')
  u=s.get(KUser,row['user_id']); u.password_hash=pw(d.password); s.execute(__import__('sqlalchemy').text("UPDATE kt_password_resets SET used=TRUE WHERE id=:id"),{'id':row['id']}); s.commit()
 return {'reset':True}
