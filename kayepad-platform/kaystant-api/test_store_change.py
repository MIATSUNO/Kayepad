import os,tempfile,uuid
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
from app import app,engine,Session,KUser,issue,datetime,UTC,timedelta
from feature_endpoints import KSpecialWallet,KEffect

def test_store_and_conversion():
 with TestClient(app) as c:
  with Session(engine) as s:
   u=KUser(email='local-test@example.org',username='tester',password_hash='hash',coins=50)
   s.add(u);s.commit();s.refresh(u);uid=u.id
   s.add(KSpecialWallet(user_id=uid,balance=500));s.commit()
  token=issue(KUser(id=uid,email='local-test@example.org',username='tester',password_hash='hash')); h={'Authorization':'Bearer '+token}
  cat=c.get('/ke-store/catalog').json();assert [(i['id'],i['price'],i['days']) for i in cat['special']]==[('cambio',60,7),('exlibris',120,7)]
  assert c.post('/special/buy',headers=h,json={'kind':'magica'}).status_code==400
  rid=str(uuid.uuid4()); d={'direction':'coins_to_special','amount':4,'request_id':rid}
  assert c.post('/special/exchange',headers=h,json=d).status_code==403
  assert c.post('/special/buy',headers=h,json={'kind':'cambio'}).status_code==200
  assert c.post('/special/buy',headers=h,json={'kind':'cambio'}).status_code==409
  r=c.post('/special/exchange',headers=h,json=d);assert r.status_code==200 and r.json()['coins']==46 and r.json()['special_coins']==460,r.text
  r=c.post('/special/exchange',headers=h,json=d);assert r.status_code==200 and r.json()['replayed'] and r.json()['special_coins']==460
  assert c.post('/special/exchange',headers=h,json={'direction':'special_to_coins','amount':6,'request_id':str(uuid.uuid4())}).status_code==422
  r=c.post('/special/exchange',headers=h,json={'direction':'special_to_coins','amount':10,'request_id':str(uuid.uuid4())});assert r.status_code==200 and r.json()['coins']==48 and r.json()['special_coins']==450
  assert c.patch('/me/exlibris',headers=h,json={'gif_url':'https://example.org/x.gif'}).status_code==403
  assert c.post('/special/buy',headers=h,json={'kind':'exlibris'}).status_code==200
  r=c.patch('/me/exlibris',headers=h,json={'gif_url':'https://example.org/x.gif','music_url':'https://example.org/song.mp3'});assert r.status_code==200,r.text
  r=c.get('/users/tester/exlibris');assert r.json()['active'] and r.json()['gif_url'].endswith('.gif')
  assert c.post('/shop/selo',headers=h).status_code==410
  with Session(engine) as s:
   for e in s.query(KEffect).all(): e.expires_at=datetime.now(UTC)-timedelta(seconds=1);s.add(e)
   s.commit()
  assert c.post('/special/exchange',headers=h,json={'direction':'coins_to_special','amount':1,'request_id':str(uuid.uuid4())}).status_code==403
  assert not c.get('/users/tester/exlibris').json()['active']
