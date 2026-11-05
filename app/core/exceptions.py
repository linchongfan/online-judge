import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details
        self.headers = headers


def error_response(request: Request, status_code: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body = {
        "error": {"code": code, "message": message, "details": jsonable_encoder(details)},
        "requestId": getattr(request.state, "request_id", None),
    }
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        response = error_response(request, exc.status_code, exc.code, exc.message, exc.details)
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(request, 422, "VALIDATION_ERROR", "请求参数校验失败", exc.errors())

    @app.exception_handler(SQLAlchemyError)
    async def database_handler(request: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.exception("Database error request_id=%s", getattr(request.state, "request_id", None))
        return error_response(request, 503, "DATABASE_UNAVAILABLE", "数据服务暂时不可用")

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error request_id=%s", getattr(request.state, "request_id", None))
        return error_response(request, 500, "INTERNAL_ERROR", "服务器内部错误")
