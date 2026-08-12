"""purchase-order-preparation phase1 입출력 형식."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

IDENTIFICATION = ("registered", "draft_created", "unidentified")
DISPOSITIONS = ("sourceable", "terms_incomplete", "no_supplier", "draft_only")


# ----------------------------------------------------------------- 입력
@dataclass
class TargetItem:
    item_code: str = ""
    item_name: str = ""
    spec: str = ""
    stock_uom: str = ""
    identification: str = "registered"      # IDENTIFICATION
    similar_candidates: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    master_price: float | None = None       # 단가 불일치 검출용


@dataclass
class SupplyTerm:
    """공급처 한 곳의 조건. 한 품목에 여러 개 올 수 있다."""
    item_code: str
    supplier: str
    unit_price: float | None = None
    price_uom: str = ""                     # 그 단가의 기준 단위
    tax: str = ""                           # included / excluded / "" (불명)
    currency: str = ""
    lead_time_days: float | None = None
    lead_time_text: str = ""                # "5~7일" 같은 원문
    lead_time_min: float | None = None
    lead_time_max: float | None = None
    moq: float | None = None
    pack_size: float | None = None
    price_breaks: list[dict] = field(default_factory=list)
    terms_note: str = ""                    # 무료배송·최소주문금액 등
    supplier_part_no: str = ""


@dataclass
class Params:
    long_lead_days: int | None = None
    lead_time_basis: str = "max"            # max / min / mid
    safety_buffer_days: int = 0
    category_scheme: list[str] = field(default_factory=list)
    tax_convention: str = "unspecified"     # included / excluded / unspecified
    base_currency: str | None = None
    auto_create_draft: bool = True
    required_terms: list[str] = field(
        default_factory=lambda: ["unit_price", "lead_time_days", "moq"])

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "Params":
        d = dict(d or {})
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ValueError(f"알 수 없는 파라미터: {sorted(unknown)}")
        p = cls(**d)
        if p.lead_time_basis not in ("max", "min", "mid"):
            raise ValueError("lead_time_basis 는 max / min / mid")
        if p.tax_convention not in ("included", "excluded", "unspecified"):
            raise ValueError("tax_convention 은 included / excluded / unspecified")
        return p

    def defaults_used(self) -> list[str]:
        base = Params()
        return [f for f in self.__dataclass_fields__
                if getattr(self, f) == getattr(base, f)]


@dataclass
class Input:
    target_items: list[TargetItem]
    supply_terms: list[SupplyTerm] = field(default_factory=list)
    need_by: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Input":
        return cls(
            target_items=[TargetItem(**r) for r in d.get("target_items", [])],
            supply_terms=[SupplyTerm(**r) for r in d.get("supply_terms", [])],
            need_by=d.get("need_by", {}) or {},
        )


# ----------------------------------------------------------------- 출력
@dataclass
class SupplyOption:
    """정규화된 공급 옵션 한 줄. 순위·추천 필드를 두지 않는다."""
    item_code: str
    supplier: str
    unit_price: float | None
    price_uom: str
    tax: str
    currency: str
    lead_time_days: float | None
    lead_time_text: str
    moq: float | None
    pack_size: float | None
    price_breaks: list[dict] = field(default_factory=list)
    terms_note: str = ""
    flags: list[str] = field(default_factory=list)


@dataclass
class BlockedItem:
    item_code: str
    disposition: str
    missing: list[str] = field(default_factory=list)
    action: str = ""


@dataclass
class Result:
    identified_items: list[dict] = field(default_factory=list)
    supply_options: list[SupplyOption] = field(default_factory=list)
    long_lead_items: list[dict] = field(default_factory=list)
    blocked_items: list[BlockedItem] = field(default_factory=list)
    draft_items_created: list[dict] = field(default_factory=list)
    disposition_summary: dict[str, int] = field(default_factory=dict)
    all_items_sourceable: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
