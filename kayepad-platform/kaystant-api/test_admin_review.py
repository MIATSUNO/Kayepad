import hashlib
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
from sqlalchemy import text
from sqlmodel import Session, select

os.environ['DATABASE_URL'] = f'sqlite:///./admin-review-{uuid.uuid4().hex}.db'
os.environ['KAYSTANT_ADMIN_USER_IDS'] = ''
os.environ.pop('KAYSTANT_ADMIN_STEP2_BCRYPT_HASH', None)
os.environ.pop('KAYSTANT_ADMIN_STEP3_SCRYPT_HASH', None)
os.environ.pop('KAYSTANT_ADMIN_STEP4_PBKDF2_HASH', None)
os.environ.pop('KAYSTANT_VERIFIED_RESET_FLOW', None)

from fastapi.testclient import TestClient
from app import app, engine, KUser, KPost


def signup(client, email, username):
    response = client.post('/auth/signup', json={
        'email': email,
        'username': username,
        'password': 'SafeReview123!',
        'full_name': username,
    })
    assert response.status_code == 200, response.text
    data = response.json()
    return data['user']['id'], data['token']


def configure_test_factors():
    answers = ['ReviewFactorTwo', 'ReviewFactorThree', 'ReviewFactorFour']
    os.environ['KAYSTANT_ADMIN_STEP2_BCRYPT_HASH'] = bcrypt.hashpw(answers[0].encode(), bcrypt.gensalt()).decode()
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(answers[1].encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    os.environ['KAYSTANT_ADMIN_STEP3_SCRYPT_HASH'] = f'scrypt$16384$8$1${salt.hex()}${digest.hex()}'
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', answers[2].encode(), salt, 100000, dklen=32)
    os.environ['KAYSTANT_ADMIN_STEP4_PBKDF2_HASH'] = f'pbkdf2-sha256$100000${salt.hex()}${digest.hex()}'
    return answers


with TestClient(app) as client:
    health = client.get('/health')
    assert health.status_code == 200
    assert health.headers['x-content-type-options'] == 'nosniff'
    assert health.headers['x-frame-options'] == 'DENY'

    admin_one_id, admin_one_token = signup(client, 'review-admin-one@gmail.com', 'reviewadminone')
    admin_two_id, admin_two_token = signup(client, 'review-admin-two@gmail.com', 'reviewadmintwo')
    user_id, user_token = signup(client, 'review-user@gmail.com', 'reviewuser')
    os.environ['KAYSTANT_ADMIN_USER_IDS'] = f'{admin_one_id}, {admin_two_id}'
    answers = configure_test_factors()

    unauthenticated = client.get('/admin/users')
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers['cache-control'].startswith('no-store')

    ordinary_stepup = client.post('/admin/step-up/start', headers={'Authorization': f'Bearer {user_token}'})
    assert ordinary_stepup.status_code == 403

    primary_admin_denied = client.get('/admin/users', headers={'Authorization': f'Bearer {admin_one_token}'})
    assert primary_admin_denied.status_code == 401

    start = client.post('/admin/step-up/start', headers={'Authorization': f'Bearer {admin_one_token}'})
    assert start.status_code == 200, start.text
    challenge = start.json()['challenge']
    assert start.json()['remaining'] == 3

    wrong = client.post('/admin/step-up/answer', headers={'Authorization': f'Bearer {admin_one_token}'}, json={'challenge': challenge, 'answer': 'incorrect'})
    assert wrong.status_code == 401

    for index, answer in enumerate(answers):
        result = client.post('/admin/step-up/answer', headers={'Authorization': f'Bearer {admin_one_token}'}, json={'challenge': challenge, 'answer': answer})
        assert result.status_code == 200, result.text
        if index < 2:
            assert result.json()['remaining'] == 2-index
    admin_token = result.json()['admin_token']

    failed_start = client.post('/admin/step-up/start', headers={'Authorization': f'Bearer {admin_one_token}'})
    assert failed_start.status_code == 200
    failed_challenge = failed_start.json()['challenge']
    for attempt in range(5):
        failed_answer = client.post('/admin/step-up/answer', headers={'Authorization': f'Bearer {admin_one_token}'}, json={'challenge': failed_challenge, 'answer': f'wrong-{attempt}'})
    assert failed_answer.status_code == 429

    authorized = client.get('/admin/users', headers={'Authorization': f'Bearer {admin_token}'})
    assert authorized.status_code == 200
    rows = {row['id']: row for row in authorized.json()}
    assert rows[admin_one_id]['is_admin'] is True
    assert rows[admin_two_id]['is_admin'] is True
    assert rows[user_id]['is_admin'] is False
    user_row = rows[user_id]
    assert {'username', 'email', 'created_at', 'display_name', 'bio', 'is_blocked', 'is_admin'} <= set(user_row)
    assert 'password_hash' not in user_row

    with Session(engine) as session:
        session.add(KPost(user_id=uuid.UUID(user_id), title='Post teste', category='texto', body='Conteúdo que não deve voltar na listagem administrativa'))
        session.commit()

    admin_posts = client.get('/admin/posts', headers={'Authorization': f'Bearer {admin_token}'})
    assert admin_posts.status_code == 200
    post_rows = admin_posts.json()
    assert len(post_rows) == 1
    assert post_rows[0]['title'] == 'Post teste'
    assert 'body' not in post_rows[0] and 'email' not in post_rows[0]

    profile_bad = client.patch('/profile', headers={'Authorization': f'Bearer {user_token}'}, json={'links': ['javascript:alert(1)']})
    assert profile_bad.status_code == 422
    profile_good = client.patch('/profile', headers={'Authorization': f'Bearer {user_token}'}, json={'links': ['https://example.org'], 'banner_url': 'https://example.org/banner.png'})
    assert profile_good.status_code == 200
    assert profile_good.json()['links'] == ['https://example.org']

    unsafe_recovery = client.post('/auth/recover-kaystant', json={'full_name': 'reviewuser', 'email': 'review-user@kaystant.org', 'username': 'reviewuser'})
    assert unsafe_recovery.status_code == 503
    disabled_reset = client.post('/auth/reset-password', json={'token': 'x' * 48, 'password': 'NewSafePassword123!'})
    assert disabled_reset.status_code == 503

    with Session(engine) as session:
        token_hash = hashlib.sha256(user_token.encode()).hexdigest()
        reset_token = secrets.token_urlsafe(48)
        session.execute(text('INSERT INTO kt_password_resets (id,user_id,token_hash,expires_at,used) VALUES (:id,:uid,:hash,:expires,FALSE)'), {
            'id': secrets.token_hex(16),
            'uid': user_id,
            'hash': hashlib.sha256(reset_token.encode()).hexdigest(),
            'expires': datetime.now(timezone.utc) + timedelta(minutes=15),
        })
        session.commit()
    os.environ['KAYSTANT_VERIFIED_RESET_FLOW'] = 'true'
    reset = client.post('/auth/reset-password', json={'token': reset_token, 'password': 'NewSafePassword123!'})
    assert reset.status_code == 200, reset.text
    replayed_reset = client.post('/auth/reset-password', json={'token': reset_token, 'password': 'AnotherSafePassword123!'})
    assert replayed_reset.status_code == 400
    revoked_session = client.get('/me', headers={'Authorization': f'Bearer {user_token}'})
    assert revoked_session.status_code == 401, (revoked_session.status_code, revoked_session.text)
    os.environ.pop('KAYSTANT_VERIFIED_RESET_FLOW', None)

    with Session(engine) as session:
        blocked_user = session.get(KUser, uuid.UUID(user_id))
        blocked_user.is_blocked = True
        session.add(blocked_user)
        session.commit()

    blocked_login = client.post('/auth/login', json={'email': 'review-user@gmail.com', 'password': 'NewSafePassword123!'})
    assert blocked_login.status_code == 403

    from admin_endpoints import KAdminSession
    with Session(engine) as session:
        admin_session = session.exec(select(KAdminSession).where(KAdminSession.token_hash == hashlib.sha256(admin_token.encode()).hexdigest())).first()
        admin_session.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.add(admin_session)
        session.commit()
    expired_admin = client.get('/admin/users', headers={'Authorization': f'Bearer {admin_token}'})
    assert expired_admin.status_code == 401

    second_start = client.post('/admin/step-up/start', headers={'Authorization': f'Bearer {admin_one_token}'})
    assert second_start.status_code == 200
    second_challenge = second_start.json()['challenge']
    for answer in answers:
        second_result = client.post('/admin/step-up/answer', headers={'Authorization': f'Bearer {admin_one_token}'}, json={'challenge': second_challenge, 'answer': answer})
        assert second_result.status_code == 200, second_result.text
        second_challenge = second_result.json().get('challenge', second_challenge)
    second_admin_token = second_result.json()['admin_token']
    assert client.get('/admin/users', headers={'Authorization': f'Bearer {second_admin_token}'}).status_code == 200

    admin_logout = client.post('/auth/logout', headers={'Authorization': f'Bearer {admin_one_token}'})
    assert admin_logout.status_code == 200
    invalidated_admin = client.get('/admin/users', headers={'Authorization': f'Bearer {second_admin_token}'})
    assert invalidated_admin.status_code == 401

print('security review tests passed')
