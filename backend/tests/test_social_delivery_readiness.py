from datetime import datetime, timezone

from app.model_defs import AgentEventLog
from app.routers.admin_agents import _compute_social_delivery_readiness


def _event(event: str, detail: dict | None = None) -> AgentEventLog:
    return AgentEventLog(
        event=event,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )


def test_readiness_requires_7d_window() -> None:
    rows = [_event("a2a_message_sent", {"routing_mode": "explicit"}) for _ in range(100)]

    totals, ready_for_flip, readiness = _compute_social_delivery_readiness(rows, window_hours=24)

    assert totals["explicit_routing_ratio_pct"] == 100.0
    assert ready_for_flip is False
    assert "window_7d" in readiness["failed_checks"]


def test_readiness_requires_explicit_ratio_at_least_95() -> None:
    rows = []
    rows.extend(_event("a2a_message_sent", {"routing_mode": "explicit"}) for _ in range(94))
    rows.extend(_event("a2a_message_sent", {"routing_mode": "text_only"}) for _ in range(6))

    totals, ready_for_flip, readiness = _compute_social_delivery_readiness(rows, window_hours=168)

    assert totals["explicit_routing_ratio_pct"] == 94.0
    assert ready_for_flip is False
    assert "explicit_ratio_target_met" in readiness["failed_checks"]


def test_readiness_requires_zero_text_only_mentions() -> None:
    rows = [_event("a2a_message_sent", {"routing_mode": "explicit"}) for _ in range(100)]
    rows.append(_event("a2a_text_only_mention_used"))

    totals, ready_for_flip, readiness = _compute_social_delivery_readiness(rows, window_hours=168)

    assert totals["a2a_text_only_mention_used"] == 1
    assert ready_for_flip is False
    assert "text_only_mention_zero" in readiness["failed_checks"]


def test_readiness_passes_on_all_conditions() -> None:
    rows = [_event("a2a_message_sent", {"routing_mode": "explicit"}) for _ in range(95)]
    rows.extend(_event("a2a_message_sent", {"routing_mode": "text_only"}) for _ in range(5))

    totals, ready_for_flip, readiness = _compute_social_delivery_readiness(rows, window_hours=168)

    assert totals["explicit_routing_ratio_pct"] == 95.0
    assert totals["a2a_text_only_mention_used"] == 0
    assert ready_for_flip is True
    assert readiness["failed_checks"] == []
