from app import app, Session, engine, select, KUser, KSession, KPost, KInk, KPurchase, KGroup, KGroupMember, KBook, KBookPost, Depends, HTTPException, me
from pydantic import BaseModel
class DeleteAccountIn(BaseModel): confirmation:str
@app.delete('/account')
def delete_account(d:DeleteAccountIn,u=Depends(me)):
 if d.confirmation!='DELETAR': raise HTTPException(400,'Digite DELETAR para confirmar')
 with Session(engine) as s:
  posts=s.exec(select(KPost).where(KPost.user_id==u.id)).all(); post_ids=[p.id for p in posts]
  for p in posts: s.delete(p)
  for model in (KSession,KPurchase):
   for row in s.exec(select(model).where(model.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KInk).where(KInk.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KGroup).where(KGroup.owner_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KGroupMember).where(KGroupMember.user_id==u.id)).all(): s.delete(row)
  s.delete(s.get(KUser,u.id));s.commit();return {'deleted':True}
