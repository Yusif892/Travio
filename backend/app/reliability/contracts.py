"""Shared contracts: verification result + retry config."""
from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Issue:
    code: str            # e.g. "BUDGET_EXCEEDED"
    message: str
    severity: Severity = Severity.ERROR


@dataclass
class RefetchRequest:
    item_id: str
    tool: str
    reason: str


@dataclass
class VerificationResult:
    issues: list[Issue] = field(default_factory=list)
    refetch_requests: list[RefetchRequest] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        blocking = {Severity.ERROR, Severity.CRITICAL}
        return not any(i.severity in blocking for i in self.issues) and not self.refetch_requests

    @property
    def severity(self) -> Severity:
        order = [Severity.INFO, Severity.WARNING, Severity.ERROR, Severity.CRITICAL]
        return max((i.severity for i in self.issues), key=order.index, default=Severity.INFO)

    def extend(self, other: "VerificationResult") -> None:
        self.issues += other.issues
        self.refetch_requests += other.refetch_requests


@dataclass
class RetryConfig:
    max_attempts: int = 3
    backoff_base: float = 0.5   # seconds
    backoff_max: float = 8.0
    timeout_s: float = 10.0
