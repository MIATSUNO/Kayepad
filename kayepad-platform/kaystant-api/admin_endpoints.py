import os
from fastapi import Depends, HTTPException
from sqlmodel import select
from app import app, Session, engine, KUser, KPost, me

def admin_required(user=Depends(me)):
    allowed_ids = {value.strip() for value in os.getenv('KAYSTANT_ADMIN_USER_IDS', '').split(',') if value.strip()}
    if not allowed_ids:
        raise HTTPException(503, 'Painel administrativo não configurado')
    if str(user.id) not in allowed_ids:
        raise HTTPException(403, 'Acesso administrativo não autorizado')
    return user

@app.get('/admin/users')
def admin_users(user=Depends(admin_required)):
    with Session(engine) as session:
        users = session.exec(select(KUser).order_by(KUser.created_at.desc())).all()
        return [
            {
                'id': str(row.id),
                'username': row.username,
                'email': row.email,
                'created_at': row.created_at.isoformat() if row.created_at else None,
                'is_blocked': bool(row.is_blocked),
            }
            for row in users
        ]

@app.get('/admin/posts')
def admin_posts(user=Depends(admin_required)):
    with Session(engine) as session:
        posts = session.exec(select(KPost).order_by(KPost.created_at.desc())).all()
        result = []
        for post in posts:
            owner = session.get(KUser, post.user_id)
            result.append(
                {
                    'id': str(post.id),
                    'user_id': str(post.user_id),
                    'username': owner.username if owner else 'conta removida',
                    'email': owner.email if owner else '',
                    'title': post.title,
                    'created_at': post.created_at.isoformat() if post.created_at else None,
                }
            )
        return result
