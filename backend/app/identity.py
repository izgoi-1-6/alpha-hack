from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Annotated
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from .clock import utc_now, as_utc
from .config import settings
from .db import get_db
from .errors import ApiError
from .models import User, AuthSession, LoginAttempt
from .schemas import LoginInput, RegisterInput, StrictModel

router = APIRouter(prefix='/auth', tags=['identity'])
Db = Annotated[Session, Depends(get_db)]
Now = Annotated[datetime, Depends(utc_now)]
COOKIE = 'credit_route_session'
password_hasher = PasswordHasher()
DUMMY_HASH = password_hasher.hash('unused-dummy-password')

def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def public_user(user: User) -> dict:
    return {key:getattr(user,key) for key in ('id','email','display_name','role')}

def get_current_user(request: Request, db: Db, now: Now) -> User:
    token = request.cookies.get(COOKIE)
    session = db.scalar(select(AuthSession).where(AuthSession.token_hash == token_digest(token))) if token else None
    if not session or session.revoked_at or as_utc(session.expires_at) <= now:
        raise ApiError(401, 'AUTH_REQUIRED', 'Войдите в свой аккаунт')
    user = db.get(User, session.user_id)
    if not user: raise ApiError(401, 'AUTH_REQUIRED', 'Войдите в свой аккаунт')
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]

def require_client(user: CurrentUser) -> User:
    if user.role != 'CLIENT': raise ApiError(403,'CLIENT_REQUIRED','Действие доступно клиенту')
    return user

def require_officer(user: CurrentUser) -> User:
    if user.role != 'CREDIT_OFFICER': raise ApiError(403,'OFFICER_REQUIRED','Требуется роль кредитного специалиста')
    return user

ClientUser = Annotated[User, Depends(require_client)]
OfficerUser = Annotated[User, Depends(require_officer)]

def check_origin(request: Request) -> None:
    if request.method in {'POST','PUT','PATCH','DELETE'} and request.headers.get('origin') != settings.ui_origin:
        raise ApiError(403,'ORIGIN_FORBIDDEN','Откройте приложение по разрешённому адресу')

def create_session(db: Session, user: User, now: datetime, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(user_id=user.id,token_hash=token_digest(token),expires_at=now+timedelta(hours=12),created_at=now))
    db.flush()
    response.set_cookie(COOKIE,token,max_age=43200,httponly=True,secure=settings.cookie_secure,samesite='lax',path='/')
    response.headers['Cache-Control']='no-store'

@router.post('/register',status_code=201)
def register(data: RegisterInput, response: Response, db: Db, now: Now):
    if db.scalar(select(User).where(User.email==data.email)):
        raise ApiError(409,'EMAIL_EXISTS','Эта почта уже зарегистрирована')
    user=User(email=data.email,password_hash=password_hasher.hash(data.password),display_name=data.display_name,role='CLIENT',created_at=now)
    db.add(user)
    db.flush()
    create_session(db,user,now,response)
    return {'user':public_user(user)}

@router.post('/login')
def login(data: LoginInput, request: Request, response: Response, db: Db, now: Now):
    bucket=token_digest(data.email+'|'+(request.client.host if request.client else 'unknown'))
    failures=db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.bucket==bucket,LoginAttempt.attempted_at>now-timedelta(minutes=15)))
    if failures >= 10:
        raise ApiError(429,'LOGIN_RATE_LIMIT','Слишком много попыток. Повторите через 15 минут.')
    user=db.scalar(select(User).where(User.email==data.email))
    try:
        verified=password_hasher.verify(user.password_hash if user else DUMMY_HASH,data.password)
    except (VerificationError, InvalidHashError):
        verified=False
    if not user or not verified:
        db.add(LoginAttempt(bucket=bucket,attempted_at=now))
        # Return an error response so the request transaction persists the failed attempt.
        return JSONResponse({'error':{'code':'INVALID_CREDENTIALS','message':'Неверная почта или пароль'}},status_code=401)
    if password_hasher.check_needs_rehash(user.password_hash):
        user.password_hash=password_hasher.hash(data.password)
    create_session(db,user,now,response)
    return {'user':public_user(user)}

@router.post('/logout',status_code=204)
def logout(data: StrictModel, request: Request, response: Response, db: Db, now: Now):
    token=request.cookies.get(COOKIE)
    session=db.scalar(select(AuthSession).where(AuthSession.token_hash==token_digest(token))) if token else None
    if session and not session.revoked_at: session.revoked_at=now
    response.delete_cookie(COOKIE,path='/',httponly=True,samesite='lax',secure=settings.cookie_secure)
    response.headers['Cache-Control']='no-store'

@router.get('/me')
def me(user: CurrentUser, response: Response):
    response.headers['Cache-Control']='no-store'
    return {'user':public_user(user)}
