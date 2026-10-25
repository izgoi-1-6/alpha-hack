from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from .config import settings
from .db import engine
from .errors import install_error_handlers
from .identity import router as auth_router, check_origin, Db
from .companies import router as companies_router
from .recommendations.router import router as recommendations_router
from .applications.router import router as applications_router
from .officer.router import router as officer_router
from .documents.router import router as documents_router
from .integrations import router as integrations_router

app=FastAPI(title='Кредитный маршрут · демо',version='0.1.0',dependencies=[Depends(check_origin)])
app.state.engine=engine
app.add_middleware(CORSMiddleware,allow_origins=[settings.ui_origin],allow_credentials=True,allow_methods=['GET','POST','PUT','PATCH','DELETE'],allow_headers=['Content-Type','Idempotency-Key'])
install_error_handlers(app)
app.include_router(auth_router,prefix='/api/v1')
app.include_router(companies_router,prefix='/api/v1')
app.include_router(recommendations_router,prefix='/api/v1')
app.include_router(applications_router,prefix='/api/v1')
app.include_router(officer_router,prefix='/api/v1')
app.include_router(documents_router,prefix='/api/v1')
app.include_router(integrations_router,prefix='/api/v1')

@app.middleware('http')
async def private_headers(request, call_next):
    response=await call_next(request)
    response.headers.setdefault('Cache-Control','no-store')  # downloads send 'private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response

@app.get('/api/v1/health')
def health(db: Db):
    db.execute(text('SELECT 1'))
    return {'status':'ok','demo_mode':settings.demo_mode}
