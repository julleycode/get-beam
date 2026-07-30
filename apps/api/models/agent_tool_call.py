"""Agent MCP tool-call metric — WS3 (agent-native-revenue) kill-test instrumentation.

One append-only row per MCP method invocation on the concierge surface
(``tools/list`` discovery calls and ``tools/call`` invocations). This is the raw
signal the GO/NO-GO kill-test report is computed from: tool-discovery rate,
tool-call rate, and param-fill rate.

Deliberately a DEDICATED table, NOT extra columns on ``agent_fetch_events`` /
``agent_visits`` (VALIDATE P4): those tables have a NOT-NULL ``vendor`` and are
populated from ``agent_classifier.classify_agent(user_agent)``, which returns
``None`` for a machine-to-machine JSON-RPC caller with no crawler UA. Recording
kill-test metrics here — keyed off the MCP request + site directly — needs no UA
classification and cannot break on a ``None`` classification. Structurally
separate from Visitor/Event and from the identity graph, same as every other
agent-surface table.

``id`` / ``created_at`` / ``updated_at`` come from ``Base``.
"""

from sqlalchemy import Boolean, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.models.database import Base


class AgentToolCall(Base):
    """Append-only per-invocation MCP tool-call metric row."""

    __tablename__ = "agent_tool_calls"
    __table_args__ = (
        Index("idx_agent_tool_calls_site_created", "site_id", "created_at"),
    )

    site_id: Mapped[str] = mapped_column(String(50), nullable=False)
    # "tools/list" (discovery) | "tools/call" (invocation)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    # For tools/call: the tool invoked (get_offers/request_quote/...). Null for
    # tools/list discovery events.
    tool_name: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Which of the required qualification params were present on this call. A
    # sanitized presence map ({param: bool}); never the raw values.
    params_provided: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # True iff all 3 required qualification params were supplied.
    params_complete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # True iff the invoked tool is a qualification-gated tool (the 3 read tools
    # under the qualification flag, or the 2 conversion tools).
    is_gated_tool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
