import pytest

from plateful.tools.menu_tools import (
    check_allergens,
    filter_by_availability,
    get_item_details,
    get_menu,
)

SAMPLE_ITEMS = [
    {
        "id": "1",
        "name": "Bowl",
        "price_usd": 15,
        "category": "healthy",
        "cuisine": "thai",
        "calories": 400,
        "allergens": ["soy"],
        "active": True,
    },
    {
        "id": "2",
        "name": "Pasta",
        "price_usd": 22,
        "category": "comfort",
        "cuisine": "italian",
        "calories": 700,
        "allergens": ["dairy", "gluten"],
        "active": True,
    },
    {"id": "3", "name": "Inactive", "price_usd": 10, "active": False},
]


@pytest.mark.unit
class TestGetMenu:
    async def test_returns_active_items(self) -> None:
        result = await get_menu(menu_data=SAMPLE_ITEMS)
        assert len(result) == 2

    async def test_filters_by_category(self) -> None:
        result = await get_menu(filters={"category": "healthy"}, menu_data=SAMPLE_ITEMS)
        assert all(i["category"] == "healthy" for i in result)

    async def test_filters_by_max_price(self) -> None:
        result = await get_menu(filters={"max_price": 16}, menu_data=SAMPLE_ITEMS)
        assert all(i["price_usd"] <= 16 for i in result)

    async def test_no_filters_returns_all_active(self) -> None:
        result = await get_menu(filters=None, menu_data=SAMPLE_ITEMS)
        assert len(result) == 2


@pytest.mark.unit
class TestCheckAllergens:
    def test_removes_allergen_items(self) -> None:
        items = [
            {"name": "A", "allergens": ["dairy"]},
            {"name": "B", "allergens": ["soy"]},
        ]
        result = check_allergens(items, ["dairy"])
        assert len(result) == 1
        assert result[0]["name"] == "B"

    def test_no_allergens_returns_all(self) -> None:
        items = [{"name": "A", "allergens": ["dairy"]}]
        result = check_allergens(items, [])
        assert len(result) == 1

    def test_case_insensitive(self) -> None:
        items = [{"name": "A", "allergens": ["Dairy"]}]
        result = check_allergens(items, ["dairy"])
        assert len(result) == 0


@pytest.mark.unit
class TestFilterByAvailability:
    def test_no_time_returns_all(self) -> None:
        items = [{"name": "A"}, {"name": "B"}]
        result = filter_by_availability(items)
        assert len(result) == 2

    def test_items_without_window_always_included(self) -> None:
        items = [{"name": "A"}]
        result = filter_by_availability(items, current_time="12:00")
        assert len(result) == 1

    def test_filters_by_time_window(self) -> None:
        items = [
            {"name": "A", "available_from": "11:00", "available_to": "14:00"},
            {"name": "B", "available_from": "17:00", "available_to": "21:00"},
        ]
        result = filter_by_availability(items, current_time="12:00")
        assert len(result) == 1
        assert result[0]["name"] == "A"


@pytest.mark.unit
class TestGetItemDetails:
    def test_finds_item_by_id(self) -> None:
        result = get_item_details("1", menu_data=SAMPLE_ITEMS)
        assert result is not None
        assert result["name"] == "Bowl"

    def test_returns_none_for_missing_id(self) -> None:
        result = get_item_details("999", menu_data=SAMPLE_ITEMS)
        assert result is None
