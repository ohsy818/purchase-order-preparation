#!/usr/bin/env python3
"""공급 조건을 정규화하고 결측·모순을 찾아낸다.

이 스크립트의 목적은 **문제를 드러내는 것**이지 값을 채우는 것이 아니다.
모르는 값은 None 으로 두고 플래그를 붙인다.
규칙은 reference/normalization-rules.md 와 일대일 대응한다.

사용:
    python normalize_terms.py --input terms.json --params params.json --output result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from schema import (  # noqa: E402
    BlockedItem, DISPOSITIONS, Input, Params, Result, SupplyOption,
)

ACTIONS = {
    "draft_only": "마스터 확정 후 재진입",
    "no_supplier": "소싱 요청",
    "terms_incomplete": "결측 조건 확인 후 재진입",
}


def _d(s: str | None) -> date | None:
    return datetime.fromisoformat(str(s)[:10]).date() if s else None


def _resolve_lead_time(t, basis: str) -> tuple[float | None, str]:
    """리드타임 확정. 원문은 언제나 보존한다."""
    text = t.lead_time_text or ""
    if t.lead_time_min is not None and t.lead_time_max is not None:
        text = text or f"{t.lead_time_min:g}~{t.lead_time_max:g}일"
        if basis == "min":
            return t.lead_time_min, text
        if basis == "mid":
            return (t.lead_time_min + t.lead_time_max) / 2, text
        return t.lead_time_max, text
    if t.lead_time_days is not None:
        return t.lead_time_days, text or f"{t.lead_time_days:g}일"
    return None, text


def normalize(data: Input, params: Params, as_of: date | None = None) -> Result:
    as_of = as_of or date.today()
    result = Result()
    by_item: dict[str, list[SupplyOption]] = defaultdict(list)

    # --- 1~4. 옵션별 정규화 -----------------------------------------------
    master_price = {i.item_code: i.master_price for i in data.target_items}
    stock_uom = {i.item_code: i.stock_uom for i in data.target_items}

    for t in data.supply_terms:
        flags: list[str] = []
        lead, lead_text = _resolve_lead_time(t, params.lead_time_basis)
        if lead is None:
            flags.append("리드타임 확인 필요")
        if t.moq is None:
            flags.append("MOQ 확인 필요")
        if t.pack_size is None and "pack_size" in params.required_terms:
            flags.append("포장 단위 확인 필요")
        if (t.moq is not None and t.pack_size is not None
                and t.moq < t.pack_size):
            flags.append("terms_conflict")

        if t.unit_price is None:
            flags.append("단가 확인 필요")
        else:
            if not t.price_uom:
                flags.append("단가 기준 단위 확인 필요")
            elif stock_uom.get(t.item_code) and t.price_uom != stock_uom[t.item_code]:
                flags.append("unit_mismatch")
            mp = master_price.get(t.item_code)
            if mp is not None and abs(mp - t.unit_price) > 1e-9:
                flags.append("price_mismatch")

        tax = t.tax or ("" if params.tax_convention == "unspecified"
                        else params.tax_convention)
        if not tax:
            flags.append("tax_unknown")
        elif not t.tax:
            flags.append(f"부가세 {tax} 로 간주 (파라미터 기준)")

        if t.currency and params.base_currency and t.currency != params.base_currency:
            flags.append("currency_diff")
        if t.price_breaks:
            flags.append("수량 구간별 단가")
        if params.long_lead_days is not None and lead is not None \
                and lead >= params.long_lead_days:
            flags.append("long_lead")

        opt = SupplyOption(
            item_code=t.item_code, supplier=t.supplier, unit_price=t.unit_price,
            price_uom=t.price_uom, tax=tax, currency=t.currency,
            lead_time_days=lead, lead_time_text=lead_text, moq=t.moq,
            pack_size=t.pack_size, price_breaks=t.price_breaks,
            terms_note=t.terms_note, flags=flags)
        by_item[t.item_code].append(opt)
        result.supply_options.append(opt)

    # 복수/단독 공급처 표시
    for code, opts in by_item.items():
        tag = "multi_source" if len(opts) > 1 else "single_source"
        for o in opts:
            o.flags.append(tag)

    # --- 5. 품목별 판정 ----------------------------------------------------
    for item in data.target_items:
        code = item.item_code or f"(미채번){item.item_name}"
        opts = by_item.get(item.item_code, [])
        missing: list[str] = []

        if item.identification == "draft_created":
            disp = "draft_only"
            missing = list(item.missing_fields)
            if params.auto_create_draft:
                result.draft_items_created.append({
                    "item_code": item.item_code, "item_name": item.item_name,
                    "spec": item.spec, "blank_fields": item.missing_fields})
        elif not opts:
            disp = "no_supplier"
        else:
            for term in params.required_terms:
                if all(getattr(o, term, None) is None for o in opts):
                    missing.append(term)
            disp = "terms_incomplete" if missing else "sourceable"

        result.identified_items.append({
            "item_code": item.item_code, "item_name": item.item_name,
            "identification": item.identification,
            "similar_candidates": item.similar_candidates,
            "missing_fields": item.missing_fields,
            "disposition": disp, "option_count": len(opts)})

        if disp != "sourceable":
            result.blocked_items.append(BlockedItem(
                item_code=code, disposition=disp, missing=missing,
                action=ACTIONS[disp]))

        # --- 7. 주문 마감일 역산 -------------------------------------------
        need = _d(data.need_by.get(item.item_code))
        for o in opts:
            if "long_lead" in o.flags and o.lead_time_days is not None:
                row = {"item_code": item.item_code, "supplier": o.supplier,
                       "lead_time_days": o.lead_time_days,
                       "lead_time_text": o.lead_time_text,
                       "need_by": data.need_by.get(item.item_code),
                       "order_deadline": None, "overdue": None}
                if need:
                    deadline = need - timedelta(
                        days=int(o.lead_time_days) + params.safety_buffer_days)
                    row["order_deadline"] = deadline.isoformat()
                    row["overdue"] = deadline < as_of
                    if row["overdue"]:
                        o.flags.append("마감 경과")
                result.long_lead_items.append(row)

    result.disposition_summary = {
        d: sum(1 for i in result.identified_items if i["disposition"] == d)
        for d in DISPOSITIONS}
    result.all_items_sourceable = not result.blocked_items

    if params.tax_convention == "unspecified":
        result.notes.append("부가세 처리가 지정되지 않아 모든 단가에 확인 필요를 표시했다")
    if params.defaults_used():
        result.notes.append("기본값 사용: " + ", ".join(params.defaults_used()))

    _verify(result, data, params)
    return result


def _verify(result: Result, data: Input, params: Params) -> None:
    """reference/normalization-rules.md 「검산」 절."""
    assert len(result.identified_items) == len(data.target_items), "분류 누락"
    assert sum(result.disposition_summary.values()) == len(data.target_items), \
        "분류 합계 불일치"

    codes = [i["item_code"] for i in result.identified_items]
    dup = {c for c in codes if codes.count(c) > 1}
    assert not dup, f"한 품목이 두 번 분류됐다: {sorted(dup)}"

    # 옵션을 버리지 않는다
    assert len(result.supply_options) == len(data.supply_terms), "공급 옵션 유실"

    # 순위·추천 필드를 두지 않는다 — 공급처 선택은 사람의 몫
    forbidden = {"rank", "score", "recommended", "best", "selected"}
    for o in result.supply_options:
        assert not (forbidden & set(vars(o))), "순위·추천 필드는 둘 수 없다"

    # sourceable 이면 required_terms 가 채워져 있어야 한다
    opts_by_item: dict[str, list] = defaultdict(list)
    for o in result.supply_options:
        opts_by_item[o.item_code].append(o)
    for i in result.identified_items:
        if i["disposition"] == "sourceable":
            opts = opts_by_item[i["item_code"]]
            for term in params.required_terms:
                assert any(getattr(o, term, None) is not None for o in opts), \
                    f"{i['item_code']}: sourceable 인데 {term} 결측"

    assert result.all_items_sourceable == (not result.blocked_items), \
        "all_items_sourceable 불일치"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = Input.from_dict(json.load(open(a.input, encoding="utf-8")))
    params = Params.from_dict(
        json.load(open(a.params, encoding="utf-8")) if a.params else None)

    out = json.dumps(normalize(data, params).to_dict(), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
