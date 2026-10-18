from app import app, Session, engine, select, KUser, KSession, KActivity, KPost, KInk, KPurchase, KGroup, KGroupMember, KBook, KBookPost, Depends, HTTPException, me
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
  from sqlalchemy import text
  # Delete dependent joins before their parent rows, using only known schema columns.
  owned_books=s.exec(select(KBook).where(KBook.owner_id==u.id)).all(); book_ids=[b.id for b in owned_books]
  if post_ids:
   for row in s.exec(select(KBookPost).where(KBookPost.post_id.in_(post_ids))).all(): s.delete(row)
  if book_ids:
   for row in s.exec(select(KBookPost).where(KBookPost.book_id.in_(book_ids))).all(): s.delete(row)
  for b in owned_books: s.delete(b)
  for p in posts: s.delete(p)
  for model in (KSession,KPurchase,KActivity):
   for row in s.exec(select(model).where(model.user_id==u.id)).all(): s.delete(row)
  for row in s.exec(select(KInk).where(KInk.user_id==u.id)).all(): s.delete(row)
  s.execute(text("DELETE FROM kt_group_members WHERE user_id = CAST(:uid AS uuid) OR group_id IN (SELECT id FROM kt_groups WHERE owner_id = CAST(:uid AS uuid))"), {'uid':str(u.id)})
  for row in s.exec(select(KGroup).where(KGroup.owner_id==u.id)).all(): s.delete(row)
  s.execute(text("DELETE FROM kt_pet_interactions WHERE visitor_id = CAST(:uid AS uuid) OR pet_id IN (SELECT id FROM kt_pets WHERE user_id = CAST(:uid AS uuid))"), {'uid':str(u.id)})
  s.execute(text("DELETE FROM kt_pets WHERE user_id = CAST(:uid AS uuid)"), {'uid':str(u.id)})
  s.delete(s.get(KUser,u.id));s.commit();return {'deleted':True}
