"""Typed error hierarchy. Every agent imports these."""


class ReliabilityError(Exception):
    """Base class for all reliability errors."""


class ToolTimeoutError(ReliabilityError):
    pass


class ToolFailureError(ReliabilityError):
    pass


class SchemaValidationError(ReliabilityError):
    pass


class ToolNotAllowedError(ReliabilityError):
    pass


class RetryExhaustedError(ReliabilityError):
    def __init__(self, task_id: str, attempts: int, last_error: Exception | None = None):
        super().__init__(f"Task {task_id} failed after {attempts} attempts: {last_error}")
        self.task_id = task_id
        self.attempts = attempts
        self.last_error = last_error