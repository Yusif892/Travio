from enum import Enum


class TaskAgent(str, Enum):
    TRANSPORTATION = "transportation"
    ACCOMMODATION = "accommodation"
    EXPERIENCES = "experiences"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class IntakeStatus(str, Enum):
    CLARIFICATION_NEEDED = "clarification_needed"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
