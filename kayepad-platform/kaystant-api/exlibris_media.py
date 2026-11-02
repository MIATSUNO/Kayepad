import os, tempfile, subprocess, json
from uuid import UUID
from datetime import datetime, timezone
from io import BytesIO
from fastapi import Request, Depends, HTTPException, Response
from sqlmodel import SQLModel, Field, Session
from sqlalchemy import Column, LargeBinary, Text
from PIL import Image, UnidentifiedImageError
from app import app, engine, me, KUser
from feature_endpoints import _lock_user, _active_effect

class KExlibrisAsset(SQLModel,table=True):
 __tablename__='kt_exlibris_assets'
 user_id:UUID=Field(primary_key=True)
 media_type:str=Field(primary_key=True)
 data:bytes=Field(sa_column=Column(LargeBinary,nullable=False))
 mime_type:str=Field(sa_column=Column(Text,nullable=False))
 updated_at:datetime=Field(default_factory=lambda:datetime.now(timezone.utc))

LIMIT=12*1024*1024

def validate_media(data):
 try:
  img=Image.open(BytesIO(data)); fmt=img.format; w,h=img.size
  if fmt in {'JPEG','PNG','GIF','WEBP'}:
   if w*h>24_000_000: raise HTTPException(422,'A imagem é grande demais')
   img.verify();return {'JPEG':'image/jpeg','PNG':'image/png','GIF':'image/gif','WEBP':'image/webp'}[fmt]
 except HTTPException:raise
 except (UnidentifiedImageError,OSError,ValueError):pass
 with tempfile.NamedTemporaryFile(prefix='exlibris-',suffix='.media') as f:
  f.write(data);f.flush()
  try:
   p=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,format_name:stream=codec_type,codec_name,width,height','-of','json',f.name],capture_output=True,timeout=12,check=True)
   details=json.loads(p.stdout); streams=details.get('streams',[]); v=[x for x in streams if x.get('codec_type')=='video']
   duration=float(details.get('format',{}).get('duration','nan')); fmt=details.get('format',{}).get('format_name','')
   if len(v)!=1 or not (0<duration<=20.05): raise HTTPException(422,'O vídeo deve ter no máximo 20 segundos')
   video=v[0]
   if video.get('width',0)*video.get('height',0)>24_000_000:raise HTTPException(422,'O vídeo é grande demais')
   if 'mp4' not in fmt or video.get('codec_name')!='h264': raise HTTPException(422,'Use um vídeo MP4 com H.264')
   return 'video/mp4'
  except HTTPException:raise
  except Exception:raise HTTPException(422,'Use JPG, PNG, GIF, WebP ou vídeo MP4 de até 20 segundos')

@app.put('/me/exlibris/banner')
async def upload_exlibris_banner(request:Request,u=Depends(me)):
 length=request.headers.get('content-length')
 if length and int(length)>LIMIT: raise HTTPException(413,'O arquivo deve ter até 12 MB')
 with Session(engine) as check:
  if not _active_effect(check,u.id,'exlibris'):raise HTTPException(403,'Ative o Ex-Libris para enviar um banner')
 chunks=[];size=0
 async for chunk in request.stream():
  size+=len(chunk)
  if size>LIMIT: raise HTTPException(413,'O arquivo deve ter até 12 MB')
  chunks.append(chunk)
 if not size:raise HTTPException(422,'Selecione um arquivo')
 data=b''.join(chunks);mime=validate_media(data)
 with Session(engine) as s:
  _lock_user(s,u.id)
  if not _active_effect(s,u.id,'exlibris'):raise HTTPException(403,'Ative o Ex-Libris para enviar um banner')
  asset=s.get(KExlibrisAsset,(u.id,'banner')) or KExlibrisAsset(user_id=u.id,media_type='banner',data=data,mime_type=mime)
  asset.data=data;asset.mime_type=mime;asset.updated_at=datetime.now(timezone.utc);s.add(asset);s.commit()
  version=str(int(asset.updated_at.timestamp()*1000))
 return {'url':f'https://kaystant-api.onrender.com/users/{u.id}/exlibris/banner?v={version}','banner_type':'video' if mime.startswith('video/') else 'image'}

@app.get('/users/{user_id}/exlibris/banner')
def public_exlibris_banner(user_id:UUID,request:Request):
 with Session(engine) as s:
  if not _active_effect(s,user_id,'exlibris'):raise HTTPException(404,'Banner indisponível')
  asset=s.get(KExlibrisAsset,(user_id,'banner'))
  if not asset:raise HTTPException(404,'Banner não encontrado')
  data=asset.data;mime=asset.mime_type
  size=len(data);r=request.headers.get('range','');headers={'Accept-Ranges':'bytes','Cache-Control':'public, max-age=60','X-Content-Type-Options':'nosniff'}
  if r.startswith('bytes='):
   try:
    first,last=r[6:].split('-',1)
    if first: start=int(first);end=int(last) if last else size-1
    else: start=max(0,size-int(last));end=size-1
    if start<0 or start>=size or end<start:raise ValueError()
    end=min(end,size-1);headers['Content-Range']=f'bytes {start}-{end}/{size}'
    return Response(data[start:end+1],status_code=206,media_type=mime,headers=headers)
   except Exception:return Response(status_code=416,headers={'Content-Range':f'bytes */{size}'})
  return Response(data,media_type=mime,headers=headers)
