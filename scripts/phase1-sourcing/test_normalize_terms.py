"""normalize_terms.py 테스트.  실행: pytest -q"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from normalize_terms import normalize                              # noqa: E402
from schema import Input, Params, SupplyTerm, TargetItem           # noqa: E402

AS_OF = date(2026, 8, 11)


def build(items, terms=(), need_by=None):
    return Input(target_items=list(items), supply_terms=list(terms),
                 need_by=need_by or {})


def opt(result, code, supplier):
    return next(o for o in result.supply_options
                if o.item_code == code and o.supplier == supplier)


# ---------------------------------------------------------------- 리드타임
@pytest.mark.parametrize("basis,expected", [("max", 7), ("min", 5), ("mid", 6)])
def test_리드타임_범위_기준(basis, expected):
    r = normalize(
        build([TargetItem("A")],
              [SupplyTerm("A", "V", unit_price=100, price_uom="EA", moq=1,
                          lead_time_min=5, lead_time_max=7)]),
        Params(lead_time_basis=basis), AS_OF)
    o = opt(r, "A", "V")
    assert o.lead_time_days == expected
    assert o.lead_time_text == "5~7일"          # 원문 보존


def test_리드타임_없으면_확인필요():
    r = normalize(build([TargetItem("A")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA", moq=1)]),
                  Params(), AS_OF)
    assert "리드타임 확인 필요" in opt(r, "A", "V").flags
    assert r.identified_items[0]["disposition"] == "terms_incomplete"


# ---------------------------------------------------------------- MOQ·포장
def test_MOQ_없으면_1로_가정하지_않는다():
    r = normalize(build([TargetItem("A")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=3)]), Params(), AS_OF)
    o = opt(r, "A", "V")
    assert o.moq is None and "MOQ 확인 필요" in o.flags


def test_MOQ가_포장단위보다_작으면_모순():
    r = normalize(build([TargetItem("A")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=3, moq=10, pack_size=12)]),
                  Params(), AS_OF)
    assert "terms_conflict" in opt(r, "A", "V").flags


# ---------------------------------------------------------------- 단가
def test_단가_기준단위가_재고단위와_다르면_환산하지_않는다():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=50000, price_uom="BOX",
                                    lead_time_days=3, moq=1)]), Params(), AS_OF)
    o = opt(r, "A", "V")
    assert o.unit_price == 50000            # 그대로
    assert "unit_mismatch" in o.flags


def test_문서단가와_마스터단가_불일치():
    r = normalize(build([TargetItem("A", stock_uom="EA", master_price=300)],
                        [SupplyTerm("A", "V", unit_price=350, price_uom="EA",
                                    lead_time_days=3, moq=1)]), Params(), AS_OF)
    assert "price_mismatch" in opt(r, "A", "V").flags


def test_부가세_불명이면_확인필요():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=3, moq=1)]), Params(), AS_OF)
    assert "tax_unknown" in opt(r, "A", "V").flags
    r2 = normalize(build([TargetItem("A", stock_uom="EA")],
                         [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                     lead_time_days=3, moq=1)]),
                   Params(tax_convention="excluded"), AS_OF)
    assert "tax_unknown" not in opt(r2, "A", "V").flags


def test_수량구간_단가는_보존된다():
    breaks = [{"min_qty": 1, "price": 5000}, {"min_qty": 10, "price": 4500}]
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=5000, price_uom="EA",
                                    lead_time_days=3, moq=1, price_breaks=breaks)]),
                  Params(), AS_OF)
    o = opt(r, "A", "V")
    assert o.price_breaks == breaks and "수량 구간별 단가" in o.flags


def test_통화가_다르면_환산하지_않는다():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    currency="USD", lead_time_days=3, moq=1)]),
                  Params(base_currency="KRW"), AS_OF)
    o = opt(r, "A", "V")
    assert o.unit_price == 100 and o.currency == "USD"
    assert "currency_diff" in o.flags


# ---------------------------------------------------------------- 판정
def test_판정_네가지():
    items = [
        TargetItem("OK", stock_uom="EA"),
        TargetItem("NOTERM", stock_uom="EA"),
        TargetItem("NOVENDOR", stock_uom="EA"),
        TargetItem("NEW", identification="draft_created", missing_fields=["moq"]),
    ]
    terms = [
        SupplyTerm("OK", "V", unit_price=100, price_uom="EA", lead_time_days=3, moq=1),
        SupplyTerm("NOTERM", "V", price_uom="EA", lead_time_days=3, moq=1),
    ]
    r = normalize(build(items, terms), Params(), AS_OF)
    got = {i["item_code"]: i["disposition"] for i in r.identified_items}
    assert got == {"OK": "sourceable", "NOTERM": "terms_incomplete",
                   "NOVENDOR": "no_supplier", "NEW": "draft_only"}
    assert r.all_items_sourceable is False
    assert len(r.blocked_items) == 3


def test_복수_공급처는_순위를_매기지_않는다():
    r = normalize(build([TargetItem("A", stock_uom="EA")], [
        SupplyTerm("A", "싼곳", unit_price=100, price_uom="EA", lead_time_days=30, moq=1),
        SupplyTerm("A", "빠른곳", unit_price=200, price_uom="EA", lead_time_days=2, moq=1),
    ]), Params(), AS_OF)
    assert len(r.supply_options) == 2
    for o in r.supply_options:
        assert "multi_source" in o.flags
        assert not ({"rank", "score", "recommended"} & set(vars(o)))


def test_단독_공급처_표시():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=3, moq=1)]), Params(), AS_OF)
    assert "single_source" in opt(r, "A", "V").flags


# ---------------------------------------------------------------- 장납기
def test_장납기와_주문마감일_역산():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=45, moq=1)],
                        need_by={"A": "2026-10-01"}),
                  Params(long_lead_days=14, safety_buffer_days=3), AS_OF)
    row = r.long_lead_items[0]
    assert row["order_deadline"] == "2026-08-14" and row["overdue"] is False


def test_마감이_지났으면_표시한다():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=45, moq=1)],
                        need_by={"A": "2026-08-20"}),
                  Params(long_lead_days=14), AS_OF)
    assert r.long_lead_items[0]["overdue"] is True
    assert "마감 경과" in opt(r, "A", "V").flags


def test_장납기_기준_미설정이면_표시하지_않는다():
    r = normalize(build([TargetItem("A", stock_uom="EA")],
                        [SupplyTerm("A", "V", unit_price=100, price_uom="EA",
                                    lead_time_days=45, moq=1)]), Params(), AS_OF)
    assert r.long_lead_items == []


# ---------------------------------------------------------------- 파라미터
def test_알수없는_파라미터는_거부한다():
    with pytest.raises(ValueError, match="알 수 없는 파라미터"):
        Params.from_dict({"long_lead_days": 14, "nope": 1})


@pytest.mark.parametrize("bad,msg", [
    ({"lead_time_basis": "avg"}, "max"),
    ({"tax_convention": "vat"}, "included"),
])
def test_잘못된_값은_거부한다(bad, msg):
    with pytest.raises(ValueError, match=msg):
        Params.from_dict(bad)


def test_공급옵션을_버리지_않는다():
    terms = [SupplyTerm("A", f"V{i}", unit_price=100, price_uom="EA",
                        lead_time_days=3, moq=1) for i in range(5)]
    r = normalize(build([TargetItem("A", stock_uom="EA")], terms), Params(), AS_OF)
    assert len(r.supply_options) == 5
