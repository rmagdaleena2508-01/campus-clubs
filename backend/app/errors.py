from fastapi import Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """An expected failure with a message safe to show the user."""

    status_code = 400

    def __init__(self, message: str, status_code: int | None = None):
        self.message = message
        if status_code is not None:
            self.status_code = status_code


class NotAuthenticated(AppError):
    status_code = 401

    def __init__(self, message: str = "Please sign in."):
        super().__init__(message)


class Forbidden(AppError):
    status_code = 403

    def __init__(self, message: str = "You are not allowed to do this."):
        super().__init__(message)


class NotFound(AppError):
    status_code = 404

    def __init__(self, message: str = "Not found."):
        super().__init__(message)


class Conflict(AppError):
    status_code = 409


class TooManyRequests(AppError):
    status_code = 429

    def __init__(self, message: str = "Too many attempts. Try again later."):
        super().__init__(message)


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"message": exc.message})
