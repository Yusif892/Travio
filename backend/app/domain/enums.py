from enum import StrEnum


class TaskAgent(StrEnum):
    TRANSPORTATION = "transportation"
    ACCOMMODATION = "accommodation"
    EXPERIENCES = "experiences"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class IntakeStatus(StrEnum):
    CLARIFICATION_NEEDED = "clarification_needed"
    REJECTED = "rejected"
    ACCEPTED = "accepted"
