import os,tempfile,uuid
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from app import app,engine,Session,KUser,issue,datetime,UTC,timedelta
from feature_endpoints import KEffect
from exlibris_media import validate_media

def test_exlibris():
 with TestClient(app) as c:
  with Session(engine) as s:
   u=KUser(email='test@example.org',username='testprofile',password_hash='hash');s.add(u);s.commit();s.refresh(u);uid=u.id
   token=issue(KUser(id=uid,email='test@example.org',username='testprofile',password_hash='hash'))
  h={'Authorization':'Bearer '+token};im=BytesIO();Image.new('RGB',(10,10),'red').save(im,'PNG');img=im.getvalue()
  assert c.put('/me/exlibris/banner',headers=h,content=img).status_code==403
  with Session(engine) as s:s.add(KEffect(user_id=uid,kind='exlibris',expires_at=datetime.now(UTC)+timedelta(days=7)));s.commit()
  assert c.put('/me/exlibris/banner',headers=h,content=b'fake').status_code==422
  r=c.put('/me/exlibris/banner',headers=h,content=img);assert r.status_code==200,r.text
  uri='/users/'+str(uid)+'/exlibris/banner';assert c.get(uri).content==img
  r=c.get(uri,headers={'Range':'bytes=0-5'});assert r.status_code==206 and r.content==img[:6]
  d={'gif_url':r.url.path,'music_url':'https://example.org/audio.mp3','music_start':34,'music_end':49}
  assert c.patch('/me/exlibris',headers=h,json=d).status_code==422
  d['gif_url']='https://example.org/banner.png';d.update(music_title='Título',music_artist='Autor',music_source_url='https://example.org',music_license='CC0')
  r=c.patch('/me/exlibris',headers=h,json=d);assert r.status_code==200,r.text
  out=c.get('/users/testprofile/exlibris').json();assert out['music_start']==34 and out['music_end']==49 and out['music_title']=='Título'
  d['music_end']=65;assert c.patch('/me/exlibris',headers=h,json=d).status_code==422
  with Session(engine) as s:
   for e in s.query(KEffect).all():e.expires_at=datetime.now(UTC)-timedelta(seconds=1);s.add(e)
   s.commit()
  assert c.get(uri).status_code==404 and not c.get('/users/testprofile/exlibris').json()['active']
