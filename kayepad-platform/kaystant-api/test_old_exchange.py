import os,tempfile,uuid
os.environ['DATABASE_URL']='sqlite:///'+tempfile.mktemp(suffix='.db')
from fastapi.testclient import TestClient
from app import app,engine,Session,KUser,issue,datetime,UTC,timedelta
from feature_endpoints import KSpecialWallet,KEffect

def test_old_exchange_limits_one_shot_expiry_and_regular():
 with TestClient(app) as c:
  with Session(engine) as s:
   u=KUser(email='old-exchange@example.invalid',username='oldexchange',password_hash='hash',coins=1000)
   s.add(u);s.commit();s.refresh(u);uid=u.id
   s.add(KSpecialWallet(user_id=uid,balance=2000));s.commit()
   tok=issue(KUser(id=uid,email=u.email,username=u.username,password_hash='hash'))
  h={'Authorization':'Bearer '+tok}
  catalog=c.get('/ke-store/catalog').json()['special']
  old=next(x for x in catalog if x['id']=='cambio_velho')
  assert (old['name'],old['price'],old['days'],old['single_use'],old['max_coins'])==('Câmbio Velho',9,3,True,100)
  r=c.post('/special/buy',headers=h,json={'kind':'cambio_velho'});assert r.status_code==200,r.text
  expiry=datetime.fromisoformat(r.json()['expires_at'].replace('Z','+00:00'));expiry=expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry
  assert timedelta(days=2,seconds=-5)<expiry-datetime.now(UTC)<timedelta(days=3,seconds=5)
  assert c.post('/special/buy',headers=h,json={'kind':'cambio_velho'}).status_code==409
  assert c.post('/special/exchange',headers=h,json={'direction':'coins_to_special','amount':101,'request_id':str(uuid.uuid4()),'kind':'cambio_velho'}).status_code==422
  rid=str(uuid.uuid4());payload={'direction':'coins_to_special','amount':100,'request_id':rid,'kind':'cambio_velho'}
  r=c.post('/special/exchange',headers=h,json=payload);assert r.status_code==200,r.text
  assert r.json()['coins']==900 and r.json()['special_coins']==2491
  replay=c.post('/special/exchange',headers=h,json=payload);assert replay.status_code==200 and replay.json()['replayed'] and replay.json()['special_coins']==2491
  assert not any(x['kind']=='cambio_velho' for x in c.get('/me/ke-wallet',headers=h).json()['effects'])
  assert c.post('/special/exchange',headers=h,json={'direction':'coins_to_special','amount':1,'request_id':str(uuid.uuid4()),'kind':'cambio_velho'}).status_code==403
  assert c.post('/special/buy',headers=h,json={'kind':'cambio_velho'}).status_code==200
  r=c.post('/special/exchange',headers=h,json={'direction':'special_to_coins','amount':501,'request_id':str(uuid.uuid4()),'kind':'cambio_velho'});assert r.status_code==422
  r=c.post('/special/exchange',headers=h,json={'direction':'special_to_coins','amount':500,'request_id':str(uuid.uuid4()),'kind':'cambio_velho'});assert r.status_code==200 and r.json()['coins']==1000 and r.json()['special_coins']==1982
  with Session(engine) as s:
   x=s.get(KUser,uid);x.coins=1000;s.add(x);w=s.get(KSpecialWallet,uid);w.balance=2000;s.add(w);s.commit()
  r=c.post('/special/buy',headers=h,json={'kind':'cambio'});assert r.status_code==200
  expiry=datetime.fromisoformat(r.json()['expires_at'].replace('Z','+00:00'));expiry=expiry.replace(tzinfo=UTC) if expiry.tzinfo is None else expiry;assert timedelta(days=6,seconds=-5)<expiry-datetime.now(UTC)<timedelta(days=7,seconds=5)
  r=c.post('/special/exchange',headers=h,json={'direction':'coins_to_special','amount':101,'request_id':str(uuid.uuid4()),'kind':'cambio'});assert r.status_code==200 and r.json()['coins']==899 and r.json()['special_coins']==2445
  with Session(engine) as s:
   old=KEffect(user_id=uid,kind='cambio_velho',value='',expires_at=datetime.now(UTC)-timedelta(seconds=1));s.add(old);s.commit()
  r=c.post('/special/exchange',headers=h,json={'direction':'coins_to_special','amount':1,'request_id':str(uuid.uuid4()),'kind':'cambio_velho'});assert r.status_code==403
