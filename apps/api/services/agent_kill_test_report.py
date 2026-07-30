"""WS3 (agent-native-revenue) kill-test GO/NO-GO report assembly.

Pure read-only aggregate over the WS3 instrumentation tables
(``agent_tool_calls`` + ``agent_leads``). Mirrors ``agent_aggregator.py``'s
read-only posture — no writes, no side effects. Supports the eventual (WS0-gated,
out-of-this-plan) wild kill test: an operator runs this over the observation
window and reads the four rates to write the signed GO/NO-GO verdict.

The four rates:
- tool_discovery_count  — count of ``tools/list`` calls (an agent found the tools)
- tool_call_count       — count of ``tools/call`` invocations
- tool_call_rate        — tool_call_count / tool_discovery_count
- param_fill_rate       — params_complete calls / tool_call_count
- lead_count            — ``agent_leads`` rows in the window
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.models.agent_lead import AgentLead
from apps.api.models.agent_tool_call import AgentToolCall


@dataclass
class KillTestReport:
    site_id: str
    window_start: datetime
    window_end: datetime
    tool_discovery_count: int
    tool_call_count: int
    param_complete_count: int
    lead_count: int
    tool_call_rate: float  # tool_call_count / tool_discovery_count (0.0 if none)
    param_fill_rate: float  # param_complete_count / tool_call_count (0.0 if none)


def _rate(numerator: int, denominator: int) -> float:
    return (numerator / denominator) if denominator else 0.0


async def assemble_kill_test_report(
    db: AsyncSession,
    site_id: str,
    window_start: datetime,
    window_end: datetime,
) -> KillTestReport:
    """Compute the four kill-test rates for one site over [start, end)."""

    def _in_window(col):
        return (col >= window_start) & (col < window_end)

    discovery = (
        await db.execute(
            select(func.count())
            .select_from(AgentToolCall)
            .where(
                AgentToolCall.site_id == site_id,
                AgentToolCall.method == "tools/list",
                _in_window(AgentToolCall.created_at),
            )
        )
    ).scalar_one()

    calls = (
        await db.execute(
            select(func.count())
            .select_from(AgentToolCall)
            .where(
                AgentToolCall.site_id == site_id,
                AgentToolCall.method == "tools/call",
                _in_window(AgentToolCall.created_at),
            )
        )
    ).scalar_one()

    complete = (
        await db.execute(
            select(func.count())
            .select_from(AgentToolCall)
            .where(
                AgentToolCall.site_id == site_id,
                AgentToolCall.method == "tools/call",
                AgentToolCall.params_complete.is_(True),
                _in_window(AgentToolCall.created_at),
            )
        )
    ).scalar_one()

    leads = (
        await db.execute(
            select(func.count())
            .select_from(AgentLead)
            .where(
                AgentLead.site_id == site_id,
                _in_window(AgentLead.created_at),
            )
        )
    ).scalar_one()

    return KillTestReport(
        site_id=site_id,
        window_start=window_start,
        window_end=window_end,
        tool_discovery_count=discovery,
        tool_call_count=calls,
        param_complete_count=complete,
        lead_count=leads,
        tool_call_rate=_rate(calls, discovery),
        param_fill_rate=_rate(complete, calls),
    )
