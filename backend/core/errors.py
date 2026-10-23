"""统一的业务异常体系。

HTTP 层只需要捕获 AppError，就能把错误码、提示语、HTTP 状态码
一起映射成统一格式的 JSON 响应，避免到处写 try/except。
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """所有可预期业务异常的基类。"""

    code: str = "internal_error"
    status: int = 500
    message: str = "服务器内部错误"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status: int | None = None,
        details: Any = None,
    ) -> None:
        super().__init__(message or self.message)
        if message:
            self.message = message
        if code:
            self.code = code
        if status:
            self.status = status
        self.details = details

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": self.code,
                "message": self.message,
            },
        }
        if self.details is not None:
            payload["error"]["details"] = self.details
        return payload


class ValidationError(AppError):
    code = "validation_error"
    status = 400
    message = "参数不合法"


class UnauthorizedError(AppError):
    code = "unauthorized"
    status = 401
    message = "请先登录"


class ForbiddenError(AppError):
    code = "forbidden"
    status = 403
    message = "没有权限执行该操作"


class NotFoundError(AppError):
    code = "not_found"
    status = 404
    message = "资源不存在"


class MethodNotAllowedError(AppError):
    code = "method_not_allowed"
    status = 405
    message = "不支持的请求方法"


class ConflictError(AppError):
    code = "conflict"
    status = 409
    message = "操作冲突"


class RateLimitError(AppError):
    code = "rate_limited"
    status = 429
    message = "操作过于频繁，请稍后再试"


class TooLargeError(AppError):
    code = "payload_too_large"
    status = 413
    message = "数据过大"


class BusinessRuleError(AppError):
    """业务规则不满足，例如「已截止的作业不能再提交」。"""

    code = "business_rule"
    status = 422
    message = "业务规则不满足"


def require(condition: bool, message: str, *, code: str = "business_rule") -> None:
    """断言式校验，条件不满足时抛 BusinessRuleError。"""
    if not condition:
        raise BusinessRuleError(message, code=code)


def ensure_found(value: Any, message: str = "资源不存在") -> Any:
    """值为 None 时抛 NotFoundError。"""
    if value is None:
        raise NotFoundError(message)
    return value
