from app import SQLModel, DBField, UUID, uuid4, datetime, UTC, BaseModel, Field, app, Session, engine, select, KUser, KPost, KSession, KInk, KPurchase, KGroup, KGroupMember, KBook, KBookPost, post_json, user_json, me, Depends, HTTPException

# Social graph and editable profiles
class KFollow(SQLModel, table=True):
 __tablename__='kt_follows'
 id:UUID=DBField(default_factory=uuid4,primary_key=True)
 follower_id:UUID=DBField(index=True)
 followed_id:UUID=DBField(index=True)
 created_at:datetime=DBField(default_factory=lambda:datetime.now(UTC))

class ProfileEdit(BaseModel):
 username:str|None=Field(default=None,min_length=3,max_length=40)
 bio:str|None=Field(default=None,max_length=280,pattern=r'^[^<>]*$')
 ink_color:str|None=Field(default=None,pattern=r'^#[0-9a-fA-F]{6}$')
 banner_url:str|None=Field(default=None,max_length=500)
 display_name:str|None=Field(default=None,max_length=80)
 show_display_name:bool|None=None
 links:list[str]|None=Field(default=None,max_length=5)
 theme:str|None=None

@app.get('/users/{username}')
def public_profile(username:str):
 with Session(engine) as s:
  u=s.exec(select(KUser).where(KUser.username==username)).first()
  if not u: raise HTTPException(404,'Perfil não encontrado')
  followers=len(s.exec(select(KFollow).where(KFollow.followed_id==u.id)).all())
  following=len(s.exec(select(KFollow).where(KFollow.follower_id==u.id)).all())
  posts=[post_json(s,p) for p in s.exec(select(KPost).where(KPost.user_id==u.id).order_by(KPost.created_at.desc())).all()]
  return {'profile':user_json(u),'followers':followers,'following':following,'posts':posts}

@app.patch('/profile')
def edit_profile(d:ProfileEdit,u=Depends(me)):
 with Session(engine) as s:
  x=s.get(KUser,u.id)
  if d.username is not None and d.username!=x.username:
   taken=s.exec(select(KUser).where(KUser.username==d.username)).first()
   if taken: raise HTTPException(409,'Este nome de usuário já está em uso')
   x.username=d.username
  for key in ('bio','ink_color','banner_url','display_name','show_display_name','theme'):
   value=getattr(d,key)
   if value is not None: setattr(x,key,value)
  if d.links is not None: x.links_json=json.dumps(d.links[:5])
  s.add(x);s.commit();s.refresh(x);return user_json(x)

@app.post('/users/{username}/follow')
def follow(username:str,u=Depends(me)):
 with Session(engine) as s:
  target=s.exec(select(KUser).where(KUser.username==username)).first()
  if not target: raise HTTPException(404,'Perfil não encontrado')
  if target.id==u.id: raise HTTPException(400,'Você não pode seguir a si mesmo')
  existing=s.exec(select(KFollow).where(KFollow.follower_id==u.id,KFollow.followed_id==target.id)).first()
  if existing: s.delete(existing); following=False
  else: s.add(KFollow(follower_id=u.id,followed_id=target.id)); following=True
  s.commit(); count=len(s.exec(select(KFollow).where(KFollow.followed_id==target.id)).all())
  return {'following':following,'followers':count}

@app.get('/users/{username}/following')
def following(username:str):
 with Session(engine) as s:
  target=s.exec(select(KUser).where(KUser.username==username)).first()
  if not target: raise HTTPException(404,'Perfil não encontrado')
  ids=s.exec(select(KFollow).where(KFollow.follower_id==target.id)).all()
  return [user_json(s.get(KUser,x.followed_id)) for x in ids]
