from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError

class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, fields: dict | None = None, details: dict | None = None):
        self.status, self.code, self.message = status, code, message
        self.fields, self.details = fields, details

def install_error_handlers(app):
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        error = {'code': exc.code, 'message': exc.message}
        if exc.fields: error['fields'] = exc.fields
        if exc.details: error['details'] = exc.details
        return JSONResponse({'error': error}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation(_request: Request, exc: RequestValidationError):
        fields = {'.'.join(str(x) for x in e['loc'] if x != 'body'): 'Проверьте значение поля' for e in exc.errors()}
        return JSONResponse({'error': {'code':'VALIDATION_ERROR','message':'Проверьте заполненные поля','fields':fields}},status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        return JSONResponse({'error':{'code':'NOT_FOUND' if exc.status_code==404 else 'HTTP_ERROR','message':'Ресурс не найден' if exc.status_code==404 else 'Запрос не может быть выполнен'}},status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def conflict(_request: Request, _exc: IntegrityError):
        return JSONResponse({'error':{'code':'RESOURCE_CONFLICT','message':'Данные уже изменились. Обновите страницу и повторите действие.'}},status_code=409)

    @app.exception_handler(Exception)
    async def unexpected(_request: Request, _exc: Exception):
        return JSONResponse({'error':{'code':'INTERNAL_ERROR','message':'Не удалось выполнить запрос. Повторите попытку.'}},status_code=500)
