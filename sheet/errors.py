"""Exceptions that the JSON API turns into HTTP error responses."""


class ApiError(Exception):
    status = 400

    def __init__(self, message, **extra):
        super().__init__(message)
        self.extra = extra  # extra JSON fields to send back with the error (e.g. per-row problems)


class BadRequest(ApiError):
    status = 400


class Forbidden(ApiError):
    status = 403
