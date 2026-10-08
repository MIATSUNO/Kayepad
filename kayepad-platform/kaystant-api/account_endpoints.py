from app import app, Session, engine, select, KUser, KSession, KPost, KInk, KPurchase, KGroup, KGroupMember, KPet, KBook, KBookPost, KPetTouch, Depends, HTTPException, me
from pydantic import BaseModel
class DeleteAccountIn(BaseModel): confirmation:str
@app.delete('/account')
def delete_account(d:DeleteAccountIn,u=Depends(me)):
 if d.confirmation!='DELETAR': raise HTTPException(400,'Digite DELETAR para confirmar')
 with Session(engine) as s:
  # Remove every social delivery edge and its dependent feedback/notices before deleting the account.
  from social_delivery_endpoints import KDelivery, KDeliveryFeedback, KDeliveryNotice
  from sqlalchemy import or_
  deliveries=s.exec(select(KDelivery).where(or_(KDelivery.sender_id==u.id,KDelivery.recipient_id==u.id))).all()
  delivery_ids=[row.id for row in deliveries]
  if delivery_ids:
   for row in s.exec(select(KDeliveryFeedback).where(KDeliveryFeedback.delivery_id.in_(delivery_ids))).all(): s.delete(row)
   for row in s.exec(select(KDeliveryNotice).where(or_(KDeliveryNotice.user_id==u.id,KDeliveryNotice.delivery_id.in_(delivery_ids)))).all(): s.delete(row)
   for row in deliveries: s.delete(row)
  posts=s.exec(select(KPost).where(KPost.user_id==u.id)).all(); post_ids=[p.id for p in posts]
  for p in posts: s.delete(p)
  for model in (KSession,KPurchase,KPet):
   for row in s.exec(select(model).where(model.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KInk).where(KInk.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KGroup).where(KGroup.owner_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KGroupMember).where(KGroupMember.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KPetTouch).where(KPetTouch.visitor_id==u.id)).all(): s.delete(row)
  s.delete(s.get(KUser,u.id));s.commit();return {'deleted':True}
