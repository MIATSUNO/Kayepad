import os, httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field
from app import app
class RecoverIn(BaseModel): email:str=Field(pattern=r'^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$')
@app.post('/auth/recover')
def recover(d:RecoverIn):
 base=os.getenv('SUPABASE_URL','').rstrip('/')
 key=os.getenv('SUPABASE_ANON_KEY','')
 if not base or not key: raise HTTPException(503,'Recuperação temporariamente indisponível')
 try:
  r=httpx.post(base+'/auth/v1/recover',headers={'apikey':key,'Content-Type':'application/json'},json={'email':str(d.email),'redirect_to':os.getenv('PASSWORD_RESET_REDIRECT','https://kayepad.neocities.org/test/')},timeout=15)
 except Exception: raise HTTPException(503,'Não foi possível enviar o e-mail agora')
 if r.status_code>=400: raise HTTPException(400,'Não foi possível enviar o e-mail para este endereço')
 return {'sent':True}
