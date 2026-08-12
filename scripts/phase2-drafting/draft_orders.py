#!/usr/bin/env python3
"""주문서 초안을 미확정 상태로 생성하고 정책 규칙을 평가한다.

절대 하지 않는 것:
  - 주문서 확정 (allow_confirm 은 켤 수 없다)
  - 승인 여부 결정 (해당 여부만 표시)
  - 거래 조건을 맞추려 수량 늘리기
  - 승인 규칙 없이 임의 기준으로 판정

규칙은 reference/quantity-rules.md, reference/approval-rules.md 와 일대일 대응한다.

사용:
    python draft_orders.py --input data.json --params params.json --output result.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from schema import (  # noqa: E402
    DraftLine, HeldItem, Input, OrderDraft, Params, PolicyAssessment, Result,
)

HAZARD_CATEGORIES = {"시약", "화학품", "용제", "시약·용제"}
EXPIRY_CATEGORIES = {"시약", "배지", "시약키트", "시약·용제"}
CALIBRATION_CATEGORIES = {"계측기", "센서", "표준물질", "분석장비 부품"}


def _d(s: str | None) -> date | None:
    return datetime.fromisoformat(str(s)[:10]).date() if s else None


# ------------------------------------------------------------------ 수량
def round_qty(need: float, moq, pack, policy: str) -> tuple[float, str]:
    """reference/quantity-rules.md 2절. 올림만 하고 절대 줄이지 않는다."""
    if policy == "none":
        return need, "none"
    qty, reasons = need, []
    if policy == "moq_then_pack":
        if moq and qty < moq:
            qty = moq
            reasons.append("moq")
        if pack:
            up = math.ceil(qty / pack) * pack
            if up != qty:
                reasons.append("pack")
            qty = up
    else:  # pack_then_moq
        if pack:
            up = math.ceil(qty / pack) * pack
            if up != qty:
                reasons.append("pack")
            qty = up
        if moq and qty < moq:
            qty = math.ceil(moq / pack) * pack if pack else moq
            reasons.append("moq")
    return qty, "+".join(reasons) if reasons else "none"


def _price_for(opt, qty: float) -> tuple[float | None, str]:
    """수량 구간별 단가가 있으면 확정 수량이 속한 구간을 쓴다."""
    if not opt.price_breaks:
        return opt.unit_price, ""
    applicable = [b for b in opt.price_breaks if qty >= b.get("min_qty", 0)]
    if not applicable:
        return opt.unit_price, ""
    best = max(applicable, key=lambda b: b.get("min_qty", 0))
    return best.get("price", opt.unit_price), \
        f"수량 {qty:g} → 구간 {best.get('min_qty')}~ 단가 적용"


# ------------------------------------------------------------------ 규칙
def _cmp(actual, op: str, value) -> bool:
    if op == "is_true":
        return bool(actual)
    if actual is None:
        return False
    if op == ">=":
        return actual >= value
    if op == ">":
        return actual > value
    if op == "<=":
        return actual <= value
    if op == "<":
        return actual < value
    if op == "==":
        return actual == value
    if op == "in":
        return actual in value
    if op == "contains":
        return value in (actual or "")
    return False


def _fmt(v):
    """근거 문장에 쓸 값 포맷. 큰 수가 지수 표기로 나가지 않게 한다."""
    if isinstance(v, bool):
        return "예" if v else "아니오"
    if isinstance(v, (int, float)):
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"
    return str(v)


def _evaluate(draft: OrderDraft, line_ctx: dict, params: Params) -> PolicyAssessment:
    rules = params.rules()
    if not rules:
        return PolicyAssessment(draft.doc_ref, "ready_to_confirm",
                                [], ["정책 미설정 — 승인 규칙이 주입되지 않아 판정하지 않음"])

    matched, evidence = [], []
    doc_vals = {
        "total_amount": draft.total_amount,
        "line_count": len(draft.lines),
        "supplier": draft.supplier,
        "max_lead_time": max((l.lead_time_days for l in draft.lines), default=0),
    }
    for r in rules:
        if r.scope == "document":
            actual = doc_vals[r.field]
            if _cmp(actual, r.operator, r.value):
                matched.append(r.name)
                evidence.append(
                    (r.evidence_template or "{actual} / 기준 {value}")
                    .replace("{actual}", _fmt(actual))
                    .replace("{value}", _fmt(r.value)).replace("{item}", draft.doc_ref))
        else:
            for line in draft.lines:
                actual = line_ctx[(draft.doc_ref, line.item_code)].get(r.field)
                if _cmp(actual, r.operator, r.value):
                    if r.name not in matched:
                        matched.append(r.name)
                    evidence.append(
                        (r.evidence_template or "{item}: {actual} / 기준 {value}")
                        .replace("{actual}", _fmt(actual))
                        .replace("{value}", _fmt(r.value))
                        .replace("{item}", line.item_name or line.item_code))
    disp = "approval_required" if matched else "ready_to_confirm"
    return PolicyAssessment(draft.doc_ref, disp, matched, evidence)


# ------------------------------------------------------------------ 본체
def draft_orders(data: Input, params: Params) -> Result:
    order_date = _d(params.order_date) or date.today()
    result = Result()
    if not params.approval_rules:
        result.notes.append(
            "승인 규칙 미주입 — 승인 판정을 하지 않았다. 모든 문서가 「정책 미설정」이다")

    opts: dict[str, list] = defaultdict(list)
    for o in data.supply_options:
        opts[o.item_code].append(o)

    # --- 1. 공급처 확정 & 보류 ---------------------------------------------
    groups: dict[tuple[str, bool], list] = defaultdict(list)
    for c in data.order_candidates:
        cand = opts.get(c.item_code, [])
        if not cand:
            result.held_items.append(HeldItem(
                c.item_code, "공급 조건 없음", "공급처 조건 확보 후 재진입"))
            continue
        if len(cand) > 1:
            sel = data.vendor_selection.get(c.item_code)
            if not sel:
                result.held_items.append(HeldItem(
                    c.item_code, "공급처 미선택 (복수 공급처)",
                    "공급처를 선택한 뒤 재진입. 임의 선택 금지"))
                continue
            match = [o for o in cand if o.supplier == sel]
            if not match:
                result.held_items.append(HeldItem(
                    c.item_code, f"선택한 공급처 '{sel}' 의 조건이 없음", "선택 재확인"))
                continue
            opt = match[0]
        else:
            opt = cand[0]

        if opt.unit_price is None:
            result.held_items.append(HeldItem(
                c.item_code, "단가 결측", "단가 확인 후 재진입. 0으로 채우지 않는다"))
            continue
        if opt.moq is None and params.rounding_policy != "none":
            result.held_items.append(HeldItem(
                c.item_code, "MOQ 결측", "MOQ 확인 후 재진입. 1로 가정하지 않는다"))
            continue
        if opt.lead_time_days is None:
            result.held_items.append(HeldItem(
                c.item_code, "리드타임 결측", "리드타임 확인 후 재진입"))
            continue

        key_supplier = opt.supplier if params.group_by_vendor else f"{opt.supplier}:{c.item_code}"
        urgent = params.split_urgent and c.urgency == "critical"
        groups[(key_supplier, urgent)].append((c, opt))

    # --- 2~5. 문서 생성 ----------------------------------------------------
    line_ctx: dict[tuple[str, str], dict] = {}
    for idx, ((key_supplier, urgent), rows) in enumerate(sorted(groups.items()), 1):
        supplier = rows[0][1].supplier
        doc_ref = f"{params.doc_prefix}-{idx:03d}" + ("-URGENT" if urgent else "")
        draft = OrderDraft(doc_ref=doc_ref, supplier=supplier, state=params.draft_state)

        for c, opt in rows:
            qty, reason = round_qty(c.net_required_qty, opt.moq, opt.pack_size,
                                    params.rounding_policy)
            price, break_note = _price_for(opt, qty)
            amount = price * qty
            due = order_date + timedelta(
                days=int(opt.lead_time_days) + params.buffer_days)

            notes: list[str] = []
            if break_note:
                notes.append(break_note)
            if reason != "none":
                notes.append(f"소요 {c.net_required_qty:g} → 주문 {qty:g} ({reason})")
            tgt = data.target_level.get(c.item_code)
            if tgt is not None and qty + data.on_hand.get(c.item_code, 0) > tgt:
                notes.append("목표재고 초과 (수량 유지)")
            if not opt.tax:
                notes.append("부가세 확인 필요")
            need = _d(data.need_by.get(c.item_code))
            if need and due > need:
                notes.append(f"납기 부족 (필요 {need.isoformat()} < 산정 {due.isoformat()})")

            draft.lines.append(DraftLine(
                item_code=c.item_code, item_name=c.item_name,
                required_qty=c.net_required_qty, order_qty=qty,
                rounding_reason=reason, unit_price=price, amount=amount,
                lead_time_days=opt.lead_time_days, due_date=due.isoformat(),
                tax=opt.tax, notes=notes))
            draft.total_amount += amount
            line_ctx[(doc_ref, c.item_code)] = {
                "amount": amount, "order_qty": qty,
                "lead_time_days": opt.lead_time_days, "is_new_item": c.is_new_item,
                "hazard_class": c.hazard_class, "category": c.category,
            }
            _special(result, doc_ref, c, opt)

        # 4. 거래 조건 — 사실만 남기고 수량은 건드리지 않는다
        terms = params.vendor_terms.get(supplier, {})
        free = terms.get("free_shipping_over")
        if free:
            if draft.total_amount >= free:
                draft.notes.append(f"무료배송 적용 (기준 {free:g}원)")
            elif draft.total_amount >= free * 0.9:
                draft.notes.append(
                    f"무료배송 기준 근접 — 합계 {draft.total_amount:g} / 기준 {free:g}. "
                    "수량은 조정하지 않았다")
        min_amt = terms.get("min_order_amount")
        if min_amt and draft.total_amount < min_amt:
            draft.notes.append(
                f"최소 주문 금액 미달 — 합계 {draft.total_amount:g} < {min_amt:g}")

        result.order_drafts.append(draft)
        result.draft_summary.append({
            "doc_ref": doc_ref, "supplier": supplier, "line_count": len(draft.lines),
            "total_amount": draft.total_amount, "state": draft.state})

    # --- 7. 정책 판정 -------------------------------------------------------
    for draft in result.order_drafts:
        result.policy_assessment.append(_evaluate(draft, line_ctx, params))
    result.requires_approval = any(
        a.disposition == "approval_required" for a in result.policy_assessment)

    if params.defaults_used():
        result.notes.append("기본값 사용: " + ", ".join(params.defaults_used()))

    _verify(result, data, params)
    return result


def _special(result: Result, doc_ref: str, c, opt) -> None:
    """reference/special-requirements.md — 애매하면 붙이는 쪽."""
    def add(req: str, why: str):
        result.special_requirements.append({
            "doc_ref": doc_ref, "item_code": c.item_code,
            "item_name": c.item_name, "requirement": req, "basis": why})

    if c.hazard_class:
        add("안전자료 첨부 필요", f"hazard_class: {c.hazard_class}")
        add("보관·운송 조건 명시", f"hazard_class: {c.hazard_class}")
    elif c.category in HAZARD_CATEGORIES:
        add("안전자료 첨부 필요", f"카테고리: {c.category}")
    if c.category in EXPIRY_CATEGORIES:
        add("잔여 유효기간 요구 조건 명시", f"카테고리: {c.category}")
    if c.category in CALIBRATION_CATEGORIES:
        add("성적서 동봉 요구", f"카테고리: {c.category}")
    if opt.currency and opt.currency != "KRW":
        add("통관 서류·원산지 증명", f"통화: {opt.currency}")


def _verify(result: Result, data: Input, params: Params) -> None:
    """reference/quantity-rules.md 「검산」 절."""
    drafted = sum(len(d.lines) for d in result.order_drafts)
    assert drafted + len(result.held_items) == len(data.order_candidates), \
        f"품목 유실: 초안 {drafted} + 보류 {len(result.held_items)} != {len(data.order_candidates)}"

    opts = {(o.item_code, o.supplier): o for o in data.supply_options}
    for d in result.order_drafts:
        assert d.state == params.draft_state, f"{d.doc_ref}: 상태가 {d.state}"
        assert "confirm" not in json.dumps(vars(d), default=str).lower(), \
            f"{d.doc_ref}: 확정 관련 흔적"
        for line in d.lines:
            assert line.order_qty >= line.required_qty, \
                f"{line.item_code}: 주문수량이 소요량보다 적다"
            o = opts.get((line.item_code, d.supplier))
            if o and o.moq and params.rounding_policy != "none":
                assert line.order_qty >= o.moq, f"{line.item_code}: MOQ 미달"
            if o and o.pack_size and params.rounding_policy != "none":
                assert abs(line.order_qty % o.pack_size) < 1e-9, \
                    f"{line.item_code}: 포장 배수 아님"

    for a in result.policy_assessment:
        if a.disposition == "approval_required":
            assert a.matched_rules and a.evidence, f"{a.doc_ref}: 근거 없는 승인 판정"

    assert result.requires_approval == any(
        a.disposition == "approval_required" for a in result.policy_assessment), \
        "requires_approval 불일치"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = Input.from_dict(json.load(open(a.input, encoding="utf-8")))
    params = Params.from_dict(
        json.load(open(a.params, encoding="utf-8")) if a.params else None)

    out = json.dumps(draft_orders(data, params).to_dict(), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
