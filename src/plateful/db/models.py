import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


# --- Enums ---


class EventType(enum.StrEnum):
    ORDER_PLACED = "order_placed"
    ITEM_ADDED = "item_added"
    ITEM_REMOVED = "item_removed"
    ITEM_SWAPPED = "item_swapped"
    SUGGESTION_ACCEPTED = "suggestion_accepted"
    SUGGESTION_REJECTED = "suggestion_rejected"
    RATING_GIVEN = "rating_given"
    MEALPLAN_EDITED = "mealplan_edited"
    ALLERGY_DECLARED = "allergy_declared"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"


class ApprovalStatus(enum.StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PolicyRuleType(enum.StrEnum):
    BUDGET_CAP = "budget_cap"
    PER_PERSON_LIMIT = "per_person_limit"
    APPROVAL_THRESHOLD = "approval_threshold"
    RESTRICTED_ITEMS = "restricted_items"


class DecisionType(enum.StrEnum):
    RECOMMENDATION = "recommendation"
    ALLERGY_FILTER = "allergy_filter"
    POLICY_CHECK = "policy_check"
    APPROVAL_ROUTE = "approval_route"
    ORDER_SUBMIT = "order_submit"


class AuditOutcome(enum.StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    OVERRIDDEN = "overridden"
    PENDING = "pending"


# --- Models ---


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    context: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)

    menu_item_links: Mapped[list["MenuItemIngredient"]] = relationship(back_populates="ingredient")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    cuisine: Mapped[str] = mapped_column(String(100), nullable=False)
    calories: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_from: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    available_to: Mapped[datetime | None] = mapped_column(Time, nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    ingredient_links: Mapped[list["MenuItemIngredient"]] = relationship(back_populates="menu_item")
    order_items: Mapped[list["OrderItem"]] = relationship(back_populates="menu_item")


class MenuItemIngredient(Base):
    __tablename__ = "menu_item_ingredients"

    menu_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("menu_items.id"), primary_key=True
    )
    ingredient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("ingredients.id"), primary_key=True
    )
    is_allergen: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    menu_item: Mapped["MenuItem"] = relationship(back_populates="ingredient_links")
    ingredient: Mapped["Ingredient"] = relationship(back_populates="menu_item_links")


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus), default=OrderStatus.PENDING, nullable=False
    )
    total_usd: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    delivery_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus), default=ApprovalStatus.NOT_REQUIRED, nullable=False
    )
    approver_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    items: Mapped[list["OrderItem"]] = relationship(back_populates="order")


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("orders.id"), nullable=False)
    item_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("menu_items.id"), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    order: Mapped["Order"] = relationship(back_populates="items")
    menu_item: Mapped["MenuItem"] = relationship(back_populates="order_items")


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    department_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    rule_type: Mapped[PolicyRuleType] = mapped_column(Enum(PolicyRuleType), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    decision_type: Mapped[DecisionType] = mapped_column(Enum(DecisionType), nullable=False)
    agent: Mapped[str] = mapped_column(String(100), nullable=False)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    output_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[AuditOutcome] = mapped_column(Enum(AuditOutcome), nullable=False)
