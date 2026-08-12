"""purchase-order-preparation phase2 입출력 형식."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

DISPOSITIONS = ("approval_required", "ready_to_confirm", "held")
ROUNDING = ("moq_then_pack", "pack_then_moq", "none")

DOC_FIELDS = ("total_amount", "line_count", "supplier", "max_lead_time")
LINE_FIELDS = ("amount", "order_qty", "lead_time_days", "is_new_item",
               "hazard_class", "category")
OPERATORS = (">=", ">", "<=", "<", "==", "in", "contains", "is_true")


# ----------------------------------------------------------------- 입력
@dataclass
class OrderCandidate:
    item_code: str
    net_required_qty: float
    item_name: str = ""
    urgency: str = "low"
    category: str = ""
    hazard_class: str = ""
    is_new_item: bool = False


@dataclass
class SupplyOption:
    """purchase-order-preparation phase1 출력에서 필요한 것만."""
    item_code: str
    supplier: str
    unit_price: float | None = None
    price_uom: str = ""
    tax: str = ""
    currency: str = ""
    lead_time_days: float | None = None
    lead_time_text: str = ""
    moq: float | None = None
    pack_size: float | None = None
    price_breaks: list[dict] = field(default_factory=list)


@dataclass
class ApprovalRule:
    name: str
    scope: str                       # document | line
    field: str
    operator: str
    value: Any = None
    evidence_template: str = ""

    def validate(self) -> None:
        if self.scope not in ("document", "line"):
            raise ValueError(f"{self.name}: scope 는 document 또는 line")
        if self.operator not in OPERATORS:
            raise ValueError(f"{self.name}: 알 수 없는 operator {self.operator}")
        allowed = DOC_FIELDS if self.scope == "document" else LINE_FIELDS
        if self.field not in allowed:
            raise ValueError(
                f"{self.name}: scope={self.scope} 에서 쓸 수 없는 field {self.field}. "
                f"가능: {allowed}")
        if self.operator != "is_true" and self.value is None:
            raise ValueError(f"{self.name}: operator {self.operator} 에는 value 필요")


@dataclass
class Params:
    approval_rules: list[dict] = field(default_factory=list)
    rounding_policy: str = "moq_then_pack"
    group_by_vendor: bool = True
    split_urgent: bool = False
    buffer_days: int = 0
    order_date: str | None = None
    draft_state: str = "draft"
    allow_confirm: bool = False
    vendor_terms: dict[str, dict] = field(default_factory=dict)
    doc_prefix: str = "DRAFT"

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Params":
        d = dict(d or {})
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"알 수 없는 파라미터: {sorted(unknown)}")
        p = cls(**d)
        if p.allow_confirm:
            raise ValueError(
                "allow_confirm 은 켤 수 없다. 주문서 확정은 사람이 실행한다 "
                "(reference/parameters.md)")
        if p.rounding_policy not in ROUNDING:
            raise ValueError(f"rounding_policy 는 {ROUNDING} 중 하나")
        for r in p.rules():
            r.validate()
        return p

    def rules(self) -> list[ApprovalRule]:
        return [ApprovalRule(**r) for r in self.approval_rules]

    def defaults_used(self) -> list[str]:
        base = Params()
        return [f for f in self.__dataclass_fields__
                if getattr(self, f) == getattr(base, f)]


@dataclass
class Input:
    order_candidates: list[OrderCandidate]
    supply_options: list[SupplyOption] = field(default_factory=list)
    vendor_selection: dict[str, str] = field(default_factory=dict)   # item -> supplier
    on_hand: dict[str, float] = field(default_factory=dict)
    target_level: dict[str, float] = field(default_factory=dict)
    need_by: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Input":
        return cls(
            order_candidates=[OrderCandidate(**r) for r in d.get("order_candidates", [])],
            supply_options=[SupplyOption(**r) for r in d.get("supply_options", [])],
            vendor_selection=d.get("vendor_selection", {}) or {},
            on_hand=d.get("on_hand", {}) or {},
            target_level=d.get("target_level", {}) or {},
            need_by=d.get("need_by", {}) or {},
        )


# ----------------------------------------------------------------- 출력
@dataclass
class DraftLine:
    item_code: str
    item_name: str
    required_qty: float
    order_qty: float
    rounding_reason: str          # moq | pack | moq+pack | none
    unit_price: float
    amount: float
    lead_time_days: float
    due_date: str
    tax: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class OrderDraft:
    doc_ref: str
    supplier: str
    state: str
    lines: list[DraftLine] = field(default_factory=list)
    total_amount: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class PolicyAssessment:
    doc_ref: str
    disposition: str
    matched_rules: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


@dataclass
class HeldItem:
    item_code: str
    reason: str
    action: str


@dataclass
class Result:
    order_drafts: list[OrderDraft] = field(default_factory=list)
    draft_summary: list[dict] = field(default_factory=list)
    special_requirements: list[dict] = field(default_factory=list)
    policy_assessment: list[PolicyAssessment] = field(default_factory=list)
    held_items: list[HeldItem] = field(default_factory=list)
    requires_approval: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
