"""Unit tests for the audit trail (store + callback factory)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from plateful.core.audit import _safe_json, make_audit_fn
from plateful.db.audit_store import _infer_decision_type, _infer_outcome
from plateful.db.models import AuditOutcome, DecisionType

# ---------------------------------------------------------------------------
# _infer_decision_type
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInferDecisionType:
    def test_recommendation(self) -> None:
        assert _infer_decision_type("recommendation", {}) == DecisionType.RECOMMENDATION

    def test_menu(self) -> None:
        assert _infer_decision_type("menu", {}) == DecisionType.ALLERGY_FILTER

    def test_policy(self) -> None:
        assert _infer_decision_type("policy", {}) == DecisionType.POLICY_CHECK

    def test_execution(self) -> None:
        assert _infer_decision_type("execution", {}) == DecisionType.ORDER_SUBMIT

    def test_unknown_defaults_to_recommendation(self) -> None:
        assert _infer_decision_type("memory", {}) == DecisionType.RECOMMENDATION


# ---------------------------------------------------------------------------
# _infer_outcome
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInferOutcome:
    def test_policy_with_violations(self) -> None:
        assert _infer_outcome("policy", {"violations": ["over budget"]}) == AuditOutcome.REJECTED

    def test_policy_without_violations(self) -> None:
        assert _infer_outcome("policy", {"violations": []}) == AuditOutcome.ACCEPTED

    def test_policy_no_violations_key(self) -> None:
        assert _infer_outcome("policy", {}) == AuditOutcome.ACCEPTED

    def test_execution_default(self) -> None:
        assert _infer_outcome("execution", {}) == AuditOutcome.ACCEPTED

    def test_unknown_defaults_to_accepted(self) -> None:
        assert _infer_outcome("learning", {}) == AuditOutcome.ACCEPTED


# ---------------------------------------------------------------------------
# _safe_json
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSafeJson:
    def test_dict_passthrough(self) -> None:
        d = {"key": "val"}
        assert _safe_json(d) is d

    def test_none_returns_empty(self) -> None:
        assert _safe_json(None) == {}

    def test_string_wraps(self) -> None:
        assert _safe_json("hello") == {"value": "hello"}

    def test_list_wraps(self) -> None:
        result = _safe_json([1, 2, 3])
        assert result == {"value": "[1, 2, 3]"}


# ---------------------------------------------------------------------------
# make_audit_fn
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMakeAuditFn:
    async def test_calls_log_audit(self) -> None:
        mock_session = AsyncMock()

        with patch("plateful.core.audit.log_audit", new_callable=AsyncMock) as mock_log:
            audit_fn = make_audit_fn(mock_session)
            await audit_fn(
                trace_id="550e8400-e29b-41d4-a716-446655440000",
                step="recommend",
                agent="recommendation",
                snapshot={"user_id": "emp_1", "intent": "get_recommendation"},
                output={"top": ["Salmon Poke Bowl"]},
            )

            mock_log.assert_called_once()
            kwargs = mock_log.call_args.kwargs
            assert kwargs["trace_id"] == "550e8400-e29b-41d4-a716-446655440000"
            assert kwargs["agent"] == "recommendation"
            assert kwargs["step"] == "recommend"
            assert kwargs["user_id"] == "emp_1"
            assert kwargs["input_snapshot"]["intent"] == "get_recommendation"
            assert kwargs["output_snapshot"]["top"] == ["Salmon Poke Bowl"]

    async def test_swallows_exception(self) -> None:
        """Audit must never break the pipeline."""
        mock_session = AsyncMock()

        with patch(
            "plateful.core.audit.log_audit", new_callable=AsyncMock, side_effect=RuntimeError("db")
        ):
            audit_fn = make_audit_fn(mock_session)
            # Should not raise
            await audit_fn(
                trace_id="550e8400-e29b-41d4-a716-446655440000",
                step="recommend",
                agent="recommendation",
                snapshot={"user_id": "emp_1"},
                output={},
            )

    async def test_safe_json_on_non_dict_output(self) -> None:
        mock_session = AsyncMock()

        with patch("plateful.core.audit.log_audit", new_callable=AsyncMock) as mock_log:
            audit_fn = make_audit_fn(mock_session)
            await audit_fn(
                trace_id="550e8400-e29b-41d4-a716-446655440000",
                step="learn",
                agent="learning",
                snapshot={"user_id": "emp_1"},
                output="preference saved",
            )

            kwargs = mock_log.call_args.kwargs
            assert kwargs["output_snapshot"] == {"value": "preference saved"}


# ---------------------------------------------------------------------------
# Audit viewer endpoints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAuditEndpoints:
    async def test_get_trace_audit(self) -> None:
        from datetime import UTC, datetime

        from plateful.api.app import app

        mock_row = MagicMock()
        mock_row.id = "row-1"
        mock_row.trace_id = "trace-1"
        mock_row.timestamp = datetime(2026, 4, 7, tzinfo=UTC)
        mock_row.user_id = "emp_1"
        mock_row.agent = "menu"
        mock_row.decision_type = DecisionType.ALLERGY_FILTER
        mock_row.input_snapshot = {"intent": "get_recommendation"}
        mock_row.output_snapshot = {"items": 11}
        mock_row.reasoning = "Agent 'menu' executed step 'retrieve'"
        mock_row.outcome = AuditOutcome.ACCEPTED

        with (
            patch("plateful.api.app.async_session_factory") as mock_factory,
            patch("plateful.db.audit_store.get_trace_audit", new_callable=AsyncMock) as mock_get,
        ):
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_get.return_value = [mock_row]

            from httpx import ASGITransport, AsyncClient

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/audit/trace/trace-1")

            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["agent"] == "menu"
            assert data[0]["decision_type"] == "allergy_filter"
