import pytest

from plateful.core.flow_router import (
    DEFAULT_FLOW,
    INTENT_FLOWS,
    get_flow_for_intent,
)


@pytest.mark.unit
class TestGetFlowForIntent:
    def test_declare_preference_skips_menu_and_recommend(self) -> None:
        flow = get_flow_for_intent("declare_preference", {"orchestrator", "learning"})
        names = [s["name"] for s in flow["steps"]]
        assert "understand" in names
        assert "learn" in names
        assert "retrieve" not in names
        assert "recommend" not in names

    def test_get_recommendation_includes_enrich_retrieve_recommend(self) -> None:
        flow = get_flow_for_intent(
            "get_recommendation",
            {"orchestrator", "memory", "menu", "recommendation"},
        )
        names = [s["name"] for s in flow["steps"]]
        assert names == ["understand", "enrich", "retrieve", "recommend"]

    def test_order_meal_includes_learn(self) -> None:
        flow = get_flow_for_intent(
            "order_meal",
            {"orchestrator", "memory", "menu", "recommendation", "learning"},
        )
        names = [s["name"] for s in flow["steps"]]
        assert "learn" in names
        assert "enrich" in names

    def test_unknown_intent_uses_default_flow(self) -> None:
        flow = get_flow_for_intent(
            "some_unknown_intent",
            {"orchestrator", "memory", "menu", "recommendation"},
        )
        names = [s["name"] for s in flow["steps"]]
        expected_names = ["understand"] + [s["name"] for s in DEFAULT_FLOW]
        assert names == expected_names

    def test_none_intent_uses_default_flow(self) -> None:
        flow = get_flow_for_intent(
            None,
            {"orchestrator", "memory", "menu", "recommendation"},
        )
        names = [s["name"] for s in flow["steps"]]
        assert "enrich" in names
        assert "recommend" in names

    def test_filters_unavailable_agents(self) -> None:
        # memory not in available agents → enrich step should be dropped
        flow = get_flow_for_intent(
            "get_recommendation",
            {"orchestrator", "menu", "recommendation"},
        )
        names = [s["name"] for s in flow["steps"]]
        assert "enrich" not in names
        assert "retrieve" in names
        assert "recommend" in names

    def test_learning_dropped_when_not_available(self) -> None:
        flow = get_flow_for_intent(
            "declare_preference",
            {"orchestrator"},  # no learning agent
        )
        names = [s["name"] for s in flow["steps"]]
        assert names == ["understand"]

    def test_understand_always_first(self) -> None:
        for intent in INTENT_FLOWS:
            flow = get_flow_for_intent(
                intent,
                {"orchestrator", "memory", "menu", "recommendation", "learning"},
            )
            assert flow["steps"][0]["name"] == "understand"

    def test_check_order_status_is_minimal(self) -> None:
        flow = get_flow_for_intent("check_order_status", {"orchestrator"})
        names = [s["name"] for s in flow["steps"]]
        assert names == ["understand"]
