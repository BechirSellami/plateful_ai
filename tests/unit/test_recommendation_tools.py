import pytest

from plateful.tools.recommendation_tools import format_recommendations_prompt, rank_items

SAMPLE_ITEMS = [
    {
        "id": "1",
        "name": "Grilled Chicken Bowl",
        "description": "Marinated chicken with rice and sweet chili",
        "price_usd": 18.50,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 450,
    },
    {
        "id": "2",
        "name": "Pasta Carbonara",
        "description": "Classic Roman pasta with guanciale",
        "price_usd": 22.00,
        "category": "comfort",
        "cuisine": "italian",
        "calories": 750,
    },
    {
        "id": "3",
        "name": "Tofu Stir Fry",
        "description": "Crispy tofu with ginger-garlic sauce",
        "price_usd": 14.00,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 350,
    },
    {
        "id": "4",
        "name": "Caesar Salad",
        "description": "Romaine lettuce with parmesan and croutons",
        "price_usd": 12.50,
        "category": "light",
        "cuisine": "italian",
        "calories": 320,
    },
]


@pytest.mark.unit
class TestRankItems:
    def test_returns_scored_items(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {})
        assert all("score" in item for item in result)

    def test_sorted_by_score_descending(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {})
        scores = [item["score"] for item in result]
        assert scores == sorted(scores, reverse=True)

    def test_healthy_category_gets_bonus(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {})
        healthy = [i for i in result if i["category"] == "healthy"]
        non_healthy = [i for i in result if i["category"] != "healthy"]
        # Healthy items should have higher base scores
        assert healthy[0]["score"] >= non_healthy[0]["score"]

    def test_cuisine_preference_boosts_score(self) -> None:
        profile = {"favorite_cuisines": ["thai"]}
        result = rank_items(SAMPLE_ITEMS, profile)
        thai_items = [i for i in result if i["cuisine"] == "thai"]
        italian_items = [i for i in result if i["cuisine"] == "italian"]
        # Thai items should outscore Italian with thai preference
        assert thai_items[0]["score"] > italian_items[0]["score"]

    def test_disliked_items_penalized(self) -> None:
        profile = {"disliked_items": ["Avoids pasta"]}
        result = rank_items(SAMPLE_ITEMS, profile)
        pasta = next(i for i in result if i["name"] == "Pasta Carbonara")
        tofu = next(i for i in result if i["name"] == "Tofu Stir Fry")
        assert pasta["score"] < tofu["score"]

    def test_preference_keywords_boost_score(self) -> None:
        profile = {"preferences": ["Loves spicy thai food"]}
        result = rank_items(SAMPLE_ITEMS, profile)
        thai_items = [i for i in result if i["cuisine"] == "thai"]
        # Thai items should be ranked higher due to keyword match
        assert result[0]["cuisine"] == "thai" or thai_items[0]["score"] >= 60

    def test_budget_preference_affects_scoring(self) -> None:
        profile = {"budget_preference": "Usually orders under $15"}
        result = rank_items(SAMPLE_ITEMS, profile)
        cheap = next(i for i in result if i["price_usd"] == 12.50)
        expensive = next(i for i in result if i["price_usd"] == 22.00)
        assert cheap["score"] > expensive["score"]

    def test_empty_profile_returns_base_scores(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {})
        # All should have at least base score
        assert all(item["score"] >= 50 for item in result)

    def test_user_message_boosts_matching_items(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {}, user_message="I want pasta")
        assert result[0]["name"] == "Pasta Carbonara"

    def test_user_message_outweighs_stored_preferences(self) -> None:
        profile = {"favorite_cuisines": ["thai"], "preferences": ["Loves spicy thai food"]}
        result = rank_items(SAMPLE_ITEMS, profile, user_message="I want pasta or a salad")
        top_names = [i["name"] for i in result[:2]]
        assert "Pasta Carbonara" in top_names
        assert "Caesar Salad" in top_names

    def test_user_message_empty_falls_back_to_profile(self) -> None:
        profile = {"favorite_cuisines": ["thai"]}
        result = rank_items(SAMPLE_ITEMS, profile, user_message="")
        # Thai items should still rank high from profile
        thai_items = [i for i in result if i["cuisine"] == "thai"]
        assert thai_items[0]["score"] > 50

    def test_empty_items_returns_empty(self) -> None:
        result = rank_items([], {"preferences": ["thai"]})
        assert result == []

    def test_preserves_original_item_data(self) -> None:
        result = rank_items(SAMPLE_ITEMS, {})
        for item in result:
            assert "name" in item
            assert "price_usd" in item
            assert "cuisine" in item


@pytest.mark.unit
class TestFormatRecommendationsPrompt:
    def test_includes_item_details(self) -> None:
        items = [
            {
                "name": "Bowl",
                "price_usd": 15,
                "category": "healthy",
                "cuisine": "thai",
                "calories": 400,
            }
        ]
        prompt = format_recommendations_prompt(items, {}, {})
        assert "Bowl" in prompt
        assert "$15" in prompt
        assert "healthy" in prompt

    def test_includes_profile_info(self) -> None:
        profile = {
            "preferences": ["spicy food"],
            "allergies": ["peanuts"],
            "dietary_restrictions": ["vegetarian"],
            "budget_preference": "under $20",
        }
        prompt = format_recommendations_prompt([], profile, {})
        assert "spicy food" in prompt
        assert "peanuts" in prompt
        assert "vegetarian" in prompt
        assert "under $20" in prompt

    def test_includes_constraints(self) -> None:
        prompt = format_recommendations_prompt([], {}, {"budget": 25, "cuisine": "thai"})
        assert "budget" in prompt
        assert "25" in prompt
        assert "thai" in prompt

    def test_handles_empty_profile(self) -> None:
        prompt = format_recommendations_prompt([], {}, {})
        assert "No profile data yet" in prompt

    def test_includes_user_message(self) -> None:
        prompt = format_recommendations_prompt(
            [], {}, {}, user_message="I want pasta or a sandwich"
        )
        assert "I want pasta or a sandwich" in prompt
        assert "current request" in prompt.lower()

    def test_no_user_message_omits_request_line(self) -> None:
        prompt = format_recommendations_prompt([], {}, {}, user_message="")
        assert "User's current request:" not in prompt

    def test_includes_scores_when_present(self) -> None:
        items = [
            {
                "name": "Bowl",
                "price_usd": 15,
                "category": "healthy",
                "cuisine": "thai",
                "calories": 400,
                "score": 75.0,
            }
        ]
        prompt = format_recommendations_prompt(items, {}, {})
        assert "75.0" in prompt
