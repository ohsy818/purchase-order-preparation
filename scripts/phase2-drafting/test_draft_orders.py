"""draft_orders.py 테스트.  실행: pytest -q"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from draft_orders import draft_orders, round_qty                      # noqa: E402
from schema import Input, OrderCandidate, Params, SupplyOption        # noqa: E402

OD = "2026-08-11"


def build(cands, opts=(), selection=None, need_by=None, target=None, on_hand=None):
    return Input(order_candidates=list(cands), supply_options=list(opts),
                 vendor_selection=selection or {}, need_by=need_by or {},
                 target_level=target or {}, on_hand=on_hand or {})


def O(code, supplier="V", price=100.0, lead=3, moq=1, pack=None, **kw):
    return SupplyOption(item_code=code, supplier=supplier, unit_price=price,
                        price_uom="EA", lead_time_days=lead, moq=moq,
                        pack_size=pack, **kw)


# ---------------------------------------------------------------- 수량 올림
@pytest.mark.parametrize("need,moq,pack,policy,qty,reason", [
    (6, 10, None, "moq_then_pack", 10, "moq"),
    (6, 1, 10, "moq_then_pack", 10, "pack"),
    (6, 10, 12, "moq_then_pack", 12, "moq+pack"),
    (6, 10, 12, "pack_then_moq", 12, "pack"),
    (56, 1, None, "moq_then_pack", 56, "none"),
    (6, 10, 12, "none", 6, "none"),
])
def test_올림_규칙(need, moq, pack, policy, qty, reason):
    assert round_qty(need, moq, pack, policy) == (qty, reason)


def test_올림은_줄이지_않는다():
    for need in (1, 7, 13, 99):
        q, _ = round_qty(need, 10, 12, "moq_then_pack")
        assert q >= need


def test_올림_사유를_메모에_남긴다():
    r = draft_orders(build([OrderCandidate("A", 6)], [O("A", moq=10)]),
                     Params(order_date=OD))
    line = r.order_drafts[0].lines[0]
    assert line.order_qty == 10 and line.rounding_reason == "moq"
    assert any("소요 6 → 주문 10" in n for n in line.notes)


# ---------------------------------------------------------------- 확정 금지
def test_allow_confirm_은_켤_수_없다():
    with pytest.raises(ValueError, match="확정은 사람이"):
        Params.from_dict({"allow_confirm": True})


def test_모든_문서가_미확정_상태():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A")]), Params(order_date=OD))
    assert all(d.state == "draft" for d in r.order_drafts)


# ---------------------------------------------------------------- 보류
@pytest.mark.parametrize("cand,opts,sel,reason", [
    (OrderCandidate("A", 5), [], None, "공급 조건 없음"),
    (OrderCandidate("A", 5), [O("A", "V1"), O("A", "V2")], None, "공급처 미선택"),
    (OrderCandidate("A", 5), [O("A", price=None)], None, "단가 결측"),
    (OrderCandidate("A", 5), [O("A", moq=None)], None, "MOQ 결측"),
    (OrderCandidate("A", 5), [O("A", lead=None)], None, "리드타임 결측"),
])
def test_보류_사유(cand, opts, sel, reason):
    r = draft_orders(build([cand], opts, sel), Params(order_date=OD))
    assert r.order_drafts == []
    assert reason in r.held_items[0].reason


def test_공급처를_선택하면_진행한다():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A", "V1"), O("A", "V2")],
                           {"A": "V2"}), Params(order_date=OD))
    assert r.order_drafts[0].supplier == "V2" and r.held_items == []


def test_단독_공급처는_선택_없이_진행():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A", "OnlyOne")]),
                     Params(order_date=OD))
    assert r.order_drafts[0].supplier == "OnlyOne"


# ---------------------------------------------------------------- 묶음
def test_같은_공급처는_한_문서로():
    r = draft_orders(build([OrderCandidate("A", 5), OrderCandidate("B", 5)],
                           [O("A", "V"), O("B", "V")]), Params(order_date=OD))
    assert len(r.order_drafts) == 1 and len(r.order_drafts[0].lines) == 2


def test_다른_공급처는_분리된다():
    r = draft_orders(build([OrderCandidate("A", 5), OrderCandidate("B", 5)],
                           [O("A", "V1"), O("B", "V2")]), Params(order_date=OD))
    assert len(r.order_drafts) == 2


def test_긴급_분리():
    cands = [OrderCandidate("A", 5, urgency="critical"), OrderCandidate("B", 5)]
    opts = [O("A", "V"), O("B", "V", lead=45)]
    one = draft_orders(build(cands, opts), Params(order_date=OD))
    assert len(one.order_drafts) == 1
    two = draft_orders(build(cands, opts), Params(order_date=OD, split_urgent=True))
    assert len(two.order_drafts) == 2


# ---------------------------------------------------------------- 납기
def test_납기_희망일_산정():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A", lead=7)]),
                     Params(order_date=OD, buffer_days=3))
    assert r.order_drafts[0].lines[0].due_date == "2026-08-21"


def test_납기_부족이어도_초안은_만든다():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A", lead=45)],
                           need_by={"A": "2026-08-20"}), Params(order_date=OD))
    line = r.order_drafts[0].lines[0]
    assert r.order_drafts != [] and any("납기 부족" in n for n in line.notes)


# ---------------------------------------------------------------- 거래 조건
def test_무료배송_근접해도_수량을_늘리지_않는다():
    r = draft_orders(build([OrderCandidate("A", 48)], [O("A", price=1000)]),
                     Params(order_date=OD,
                            vendor_terms={"V": {"free_shipping_over": 50000}}))
    assert r.order_drafts[0].lines[0].order_qty == 48        # 그대로
    assert any("근접" in n for n in r.order_drafts[0].notes)


def test_최소_주문금액_미달_표시():
    r = draft_orders(build([OrderCandidate("A", 1)], [O("A", price=1000)]),
                     Params(order_date=OD,
                            vendor_terms={"V": {"min_order_amount": 100000}}))
    assert any("최소 주문 금액 미달" in n for n in r.order_drafts[0].notes)


def test_목표재고_초과는_표시만_하고_수량_유지():
    r = draft_orders(build([OrderCandidate("A", 6)], [O("A", moq=10)],
                           target={"A": 8}), Params(order_date=OD))
    line = r.order_drafts[0].lines[0]
    assert line.order_qty == 10
    assert any("목표재고 초과" in n for n in line.notes)


def test_수량_구간별_단가는_확정수량_기준():
    o = O("A", price=5000, moq=1,
          price_breaks=[{"min_qty": 1, "price": 5000}, {"min_qty": 10, "price": 4500}])
    r = draft_orders(build([OrderCandidate("A", 12)], [o]), Params(order_date=OD))
    assert r.order_drafts[0].lines[0].unit_price == 4500


# ---------------------------------------------------------------- 승인 규칙
RULES = [
    {"name": "고액", "scope": "document", "field": "total_amount",
     "operator": ">=", "value": 500000,
     "evidence_template": "합계 {actual}원 ≥ 기준 {value}원"},
    {"name": "장납기", "scope": "line", "field": "lead_time_days",
     "operator": ">=", "value": 14,
     "evidence_template": "{item} 리드타임 {actual}일 ≥ {value}일"},
    {"name": "위험물", "scope": "line", "field": "hazard_class",
     "operator": "is_true", "evidence_template": "{item} 은 규제 대상"},
]


def test_규칙이_없으면_판정하지_않는다():
    r = draft_orders(build([OrderCandidate("A", 5)], [O("A", price=99999999)]),
                     Params(order_date=OD))
    a = r.policy_assessment[0]
    assert a.disposition == "ready_to_confirm" and a.matched_rules == []
    assert "정책 미설정" in a.evidence[0]
    assert r.requires_approval is False


def test_큰_금액이_지수표기로_나가지_않는다():
    r = draft_orders(build([OrderCandidate("A", 100)], [O("A", price=32000)]),
                     Params(order_date=OD, approval_rules=RULES))
    ev = r.policy_assessment[0].evidence[0]
    assert "3,200,000원" in ev and "e+" not in ev


def test_고액_규칙():
    r = draft_orders(build([OrderCandidate("A", 10)], [O("A", price=89000)]),
                     Params(order_date=OD, approval_rules=RULES))
    a = r.policy_assessment[0]
    assert a.disposition == "approval_required" and "고액" in a.matched_rules
    assert "890,000원" in a.evidence[0]
    assert r.requires_approval is True


def test_규칙이_겹치면_모두_기록된다():
    c = OrderCandidate("A", 10, item_name="타겟", hazard_class="")
    r = draft_orders(build([c], [O("A", price=89000, lead=45)]),
                     Params(order_date=OD, approval_rules=RULES))
    assert set(r.policy_assessment[0].matched_rules) == {"고액", "장납기"}
    assert len(r.policy_assessment[0].evidence) == 2


def test_품목단위_규칙은_한_건만_걸려도_문서_전체가_대상():
    cands = [OrderCandidate("A", 1, item_name="일반"),
             OrderCandidate("B", 1, item_name="용제A", hazard_class="생식독성")]
    r = draft_orders(build(cands, [O("A"), O("B")]),
                     Params(order_date=OD, approval_rules=RULES))
    a = r.policy_assessment[0]
    assert a.disposition == "approval_required" and "위험물" in a.matched_rules


def test_승인_판정에는_근거가_있어야_한다():
    r = draft_orders(build([OrderCandidate("A", 10, item_name="X")],
                           [O("A", price=89000)]),
                     Params(order_date=OD, approval_rules=RULES))
    for a in r.policy_assessment:
        if a.disposition == "approval_required":
            assert a.evidence


@pytest.mark.parametrize("bad,msg", [
    ({"name": "x", "scope": "doc", "field": "total_amount", "operator": ">=", "value": 1},
     "scope 는"),
    ({"name": "x", "scope": "document", "field": "total_amount", "operator": "~=", "value": 1},
     "operator"),
    ({"name": "x", "scope": "document", "field": "hazard_class", "operator": "is_true"},
     "쓸 수 없는 field"),
    ({"name": "x", "scope": "document", "field": "total_amount", "operator": ">="},
     "value 필요"),
])
def test_잘못된_규칙은_거부한다(bad, msg):
    with pytest.raises(ValueError, match=msg):
        Params.from_dict({"approval_rules": [bad]})


# ---------------------------------------------------------------- 특수 요건
def test_위험물은_안전자료_요건이_붙는다():
    c = OrderCandidate("A", 5, item_name="IPA", hazard_class="인화성")
    r = draft_orders(build([c], [O("A")]), Params(order_date=OD))
    reqs = [s["requirement"] for s in r.special_requirements]
    assert any("안전자료" in x for x in reqs) and any("보관" in x for x in reqs)


def test_특수요건은_승인판정과_별개다():
    c = OrderCandidate("A", 1, item_name="IPA", hazard_class="인화성")
    r = draft_orders(build([c], [O("A", price=100)]), Params(order_date=OD))
    assert r.special_requirements                      # 요건은 붙고
    assert r.requires_approval is False                # 승인 판정은 안 한다


# ---------------------------------------------------------------- 검산
def test_품목이_유실되지_않는다():
    cands = [OrderCandidate(c, 5) for c in "ABCDE"]
    opts = [O("A"), O("B"), O("C", price=None), O("D", "V1"), O("D", "V2")]
    r = draft_orders(build(cands, opts), Params(order_date=OD))
    drafted = sum(len(d.lines) for d in r.order_drafts)
    assert drafted + len(r.held_items) == 5


def test_알수없는_파라미터는_거부한다():
    with pytest.raises(ValueError, match="알 수 없는 파라미터"):
        Params.from_dict({"buffer_days": 3, "nope": 1})
