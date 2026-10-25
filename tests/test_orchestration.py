import asyncio
from datetime import date
from decimal import Decimal

from app.agents.supervisor import Supervisor
from app.domain.enums import TaskAgent, TaskStatus
from app.domain.schemas import TripRecord, TripRequest
from app.services.orchestration import PlanningOrchestrator


def record(message="plan my complete trip"):
    return TripRecord(trip_request=TripRequest(origin="Cairo", destination="Rome", departure_date=date(2027, 5, 1),
                      return_date=date(2027, 5, 7), budget=Decimal("1500"), travelers=2),
                      messages=[{"role": "user", "content": message}])


def test_flights_only_runs_transportation():
    seen = []
    async def transport(_: dict): seen.append("transport"); return [{"id": "f1"}]
    async def other(_: dict): seen.append("other"); return []
    orchestrator = PlanningOrchestrator(agents={TaskAgent.TRANSPORTATION: transport, TaskAgent.ACCOMMODATION: other, TaskAgent.EXPERIENCES: other})
    trip = asyncio.run(orchestrator.run(record("find flights; I already have a hotel")))
    assert seen == ["transport"]
    assert [task.agent for task in trip.tasks] == [TaskAgent.TRANSPORTATION]


def test_full_trip_fans_out_and_preserves_success_when_one_fails():
    seen = []
    async def good(name):
        async def inner(_: dict): seen.append(name); await asyncio.sleep(.01); return [{"agent": name}]
        return inner
    async def broken(_: dict): seen.append("lodging"); raise RuntimeError("provider unavailable")
    agents = {TaskAgent.TRANSPORTATION: asyncio.run(good("transport")), TaskAgent.ACCOMMODATION: broken,
              TaskAgent.EXPERIENCES: asyncio.run(good("experience"))}
    trip = asyncio.run(PlanningOrchestrator(agents=agents).run(record()))
    assert set(seen) == {"transport", "lodging", "experience"}
    assert trip.transport_options and trip.experience_options
    assert next(task for task in trip.tasks if task.agent is TaskAgent.ACCOMMODATION).status is TaskStatus.FAILED


def test_retry_only_reinvokes_failed_task():
    calls = []
    async def transport(_: dict): calls.append("transport"); return []
    async def lodging(_: dict): calls.append("lodging"); return []
    agents = {TaskAgent.TRANSPORTATION: transport, TaskAgent.ACCOMMODATION: lodging, TaskAgent.EXPERIENCES: lodging}
    trip = record("find flights and hotel")
    service = PlanningOrchestrator(agents=agents)
    asyncio.run(service.run(trip))
    trip.tasks[1].status = TaskStatus.FAILED
    asyncio.run(service.run(trip, retry_only=True))
    assert calls == ["transport", "lodging", "lodging"]
