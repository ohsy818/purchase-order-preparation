"""purchase-order-preparation 진입점.

두 단계를 순서대로 돌리고 결과를 하나로 합친다.

  phase1-sourcing   품목 식별 + 공급 조건 정규화·비교
  phase2-drafting   주문수량 올림 · 납기 산정 · 주문서 초안 · 정책 판정

phase2는 phase1이 낸 공급 조건을 그대로 받는다. 재조회하지 않는다.
주문서는 반드시 미확정 상태로 남는다. 확정은 사람이 한다.

사용법
  python run.py --input data.json --params params.json [--output out.json]

입력(data.json)
  {
    "order_candidates": [{"item_code","item_name","net_required_qty",
                          "urgency","category","hazard_class","is_new_item"}],
    "target_items":     [{"item_code","item_name","spec","stock_uom",
                          "identification","similar_candidates",
                          "missing_fields","master_price"}],
    "supply_terms":     [{"item_code","supplier","unit_price","lead_time_days",
                          "moq","pack_size","tax","currency","lead_time_text",...}],
    "vendor_selection": {"품목": "공급처"},        (선택 — 사람이 고른 결과)
    "on_hand":          {"품목": 수량},            (선택)
    "target_level":     {"품목": 수량},            (선택)
    "need_by":          {"품목": "ISO날짜"}        (선택)
  }

  target_items 를 생략하면 order_candidates 로 자동 구성한다.

파라미터(params.json) — 단계별로 나눠서 넣는다
  {"sourcing": {...}, "drafting": {...}}

  drafting.approval_rules 를 주지 않으면 정책 판정을 하지 않는다.
  기본 승인 기준을 스스로 만들지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
P1 = os.path.join(HERE, "phase1-sourcing", "normalize_terms.py")
P2 = os.path.join(HERE, "phase2-drafting", "draft_orders.py")


def _run(script: str, data: dict, params: dict) -> dict:
    with tempfile.TemporaryDirectory() as d:
        di = os.path.join(d, "in.json")
        pi = os.path.join(d, "params.json")
        json.dump(data, open(di, "w", encoding="utf-8"), ensure_ascii=False)
        json.dump(params or {}, open(pi, "w", encoding="utf-8"), ensure_ascii=False)
        r = subprocess.run([sys.executable, script, "--input", di, "--params", pi],
                           capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"{os.path.basename(script)} 실패\n{r.stderr}")
    return json.loads(r.stdout)


_TARGET_FIELDS = ("item_code", "item_name", "spec", "stock_uom",
                  "identification", "similar_candidates", "missing_fields",
                  "master_price")

# phase1 은 비교용 부가 정보(terms_note·flags 등)를 함께 낸다.
# phase2 는 주문서를 만드는 데 쓰는 필드만 받는다.
_OPTION_FIELDS = ("item_code", "supplier", "unit_price", "price_uom", "tax",
                  "currency", "lead_time_days", "lead_time_text", "moq",
                  "pack_size", "price_breaks")


def prepare(data: dict, params: dict) -> dict:
    params = params or {}
    candidates = data.get("order_candidates", [])

    targets = data.get("target_items")
    if targets is None:
        targets = [{"item_code": c["item_code"], "item_name": c.get("item_name", "")}
                   for c in candidates]
    targets = [{k: v for k, v in t.items() if k in _TARGET_FIELDS} for t in targets]

    # ── phase 1 ────────────────────────────────────────────────
    src = _run(P1, {
        "target_items": targets,
        "supply_terms": data.get("supply_terms", []),
    }, params.get("sourcing", {}))

    # ── phase 1 → phase 2 인계 ─────────────────────────────────
    # 보류된 품목은 주문서 단계로 넘기지 않는다. 값이 빈 문서가 나온다.
    blocked = {b["item_code"] for b in src["blocked_items"]}
    passed = [c for c in candidates if c["item_code"] not in blocked]
    held = [{"item_code": c["item_code"],
             "item_name": c.get("item_name", ""),
             "net_required_qty": c["net_required_qty"],
             "reason": next(b["disposition"] for b in src["blocked_items"]
                            if b["item_code"] == c["item_code"]),
             "action": next(b.get("action", "") for b in src["blocked_items"]
                            if b["item_code"] == c["item_code"])}
            for c in candidates if c["item_code"] in blocked]

    drafts = {"order_drafts": [], "draft_summary": [], "special_requirements": [],
              "policy_assessment": [], "held_items": [], "requires_approval": False,
              "notes": []}
    if passed:
        options = [{k: v for k, v in o.items() if k in _OPTION_FIELDS}
                   for o in src["supply_options"]]
        drafts = _run(P2, {
            "order_candidates": passed,
            "supply_options": options,
            "vendor_selection": data.get("vendor_selection", {}),
            "on_hand": data.get("on_hand", {}),
            "target_level": data.get("target_level", {}),
            "need_by": data.get("need_by", {}),
        }, params.get("drafting", {}))

    # ── 검산 ───────────────────────────────────────────────────
    for d in drafts["order_drafts"]:
        assert d["state"] == params.get("drafting", {}).get("draft_state", "draft"), \
            f"{d['doc_ref']}: 미확정 상태가 아니다"
    drafted = {l["item_code"] for d in drafts["order_drafts"] for l in d["lines"]}
    for code in drafted:
        assert code not in blocked, f"{code}: 보류 품목으로 문서를 만들었다"

    return {
        "sourcing": src,
        "drafting": drafts,
        # 프로세스가 바로 쓰는 값
        "order_drafts": drafts["order_drafts"],
        "requires_approval": drafts["requires_approval"],
        # 사람이 보완해야 하는 것 — 반드시 폼에 노출한다
        "blocked_items": src["blocked_items"],
        "held_items": drafts["held_items"] + held,
        "notes": src.get("notes", []) + drafts.get("notes", []),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="공급 조건을 정리해 주문서 초안까지 만든다")
    ap.add_argument("--input", required=True)
    ap.add_argument("--params")
    ap.add_argument("--output")
    a = ap.parse_args()

    data = json.load(open(a.input, encoding="utf-8"))
    params = json.load(open(a.params, encoding="utf-8")) if a.params else {}

    out = json.dumps(prepare(data, params), ensure_ascii=False, indent=2)
    if a.output:
        open(a.output, "w", encoding="utf-8").write(out)
        print(f"wrote {a.output}")
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
