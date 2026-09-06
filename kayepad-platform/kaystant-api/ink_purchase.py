# Ink purchase endpoint kept separate from the Ke-Store catalog.
from app import app, Session, engine, select, KUser, me, Depends, HTTPException, user_json
@app.post('/ink-shop/buy')
def buy_ink(u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  if x.coins<100: raise HTTPException(400,'São necessários 100 Coins para comprar 50 Tintas')
  x.coins-=100;x.ink+=50;s.add(x);s.commit();return {'coins':x.coins,'ink':x.ink,'purchased':50}
