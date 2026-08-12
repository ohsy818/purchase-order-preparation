# 승인 규칙

이 스킬은 **기본 정책을 갖지 않는다.** 규칙을 받지 못하면 판정하지 않는다.
조직이 정하지 않은 기준으로 결재가 갈리면 통제가 무력화되기 때문이다.

## 규칙 형식

```json
{
  "name": "고액",
  "scope": "document",
  "field": "total_amount",
  "operator": ">=",
  "value": 500000,
  "evidence_template": "합계 {actual}원 ≥ 기준 {value}원"
}
```

| 키 | 필수 | 값 |
|---|---|---|
| `name` | ● | 규칙 이름. 리포트에 그대로 나온다 |
| `scope` | ● | `document` (문서 단위) / `line` (품목 단위) |
| `field` | ● | 평가할 필드. 아래 표 참조 |
| `operator` | ● | `>=` `>` `<=` `<` `==` `in` `contains` `is_true` |
| `value` | ○ | 비교값. `is_true`면 생략 |
| `evidence_template` | ○ | 근거 문장. `{actual}` `{value}` `{item}` 치환 |

## 평가 가능한 필드

**`scope: "document"`**

| 필드 | 뜻 |
|---|---|
| `total_amount` | 문서 합계 금액 |
| `line_count` | 품목 수 |
| `supplier` | 공급처명 |
| `max_lead_time` | 문서 내 최장 리드타임 |

**`scope: "line"`**

| 필드 | 뜻 |
|---|---|
| `amount` | 품목별 금액 |
| `order_qty` | 주문수량 |
| `lead_time_days` | 리드타임 |
| `is_new_item` | 신규 등록 품목 여부 |
| `hazard_class` | 위험물 분류 |
| `category` | 카테고리 |

`line` 규칙은 **한 품목이라도 해당하면** 그 문서 전체가 승인 대상이 된다.

## 작성 예

```json
[
  {"name": "고액", "scope": "document", "field": "total_amount",
   "operator": ">=", "value": 500000,
   "evidence_template": "합계 {actual}원 ≥ 기준 {value}원"},

  {"name": "위험물", "scope": "line", "field": "hazard_class",
   "operator": "is_true",
   "evidence_template": "{item} 은 규제 대상 물질"},

  {"name": "장납기", "scope": "line", "field": "lead_time_days",
   "operator": ">=", "value": 14,
   "evidence_template": "{item} 리드타임 {actual}일 ≥ {value}일"},

  {"name": "신규품목", "scope": "line", "field": "is_new_item",
   "operator": "is_true",
   "evidence_template": "{item} 은 이번에 신규 등록됨"}
]
```

## 규칙을 정할 때 생각할 것

**근거를 남길 수 있는 규칙만 쓴다**
`evidence_template`을 쓸 수 없는 규칙은 승인자가 무엇을 봐야 할지 모른다.
"뭔가 걸렸다"만으로는 검토가 되지 않는다.

**규칙이 겹쳐도 된다**
고액이면서 장납기면 두 규칙 모두 기록된다. 하나만 남기지 않는다.
승인자가 두 가지를 다 봐야 한다.

**금액 기준은 문서 단위인지 품목 단위인지 분명히**
품목 단위로 걸면 소액 품목 여러 개가 합쳐진 큰 문서를 놓친다.
문서 단위로만 걸면 고가 품목 하나가 든 소액 문서를 놓친다.
둘 다 필요하면 규칙을 두 개 쓴다.

**규칙이 없는 것과 규칙이 0건 걸린 것은 다르다**
전자는 「정책 미설정」, 후자는 「바로 확정 가능」이다.
리포트에서 반드시 구분한다.

## 판정 결과 형식

```json
{
  "doc_ref": "DRAFT-001",
  "disposition": "approval_required",
  "matched_rules": ["고액", "장납기"],
  "evidence": [
    "합계 890000원 ≥ 기준 500000원",
    "GC컬럼 리드타임 45일 ≥ 14일"
  ]
}
```

`matched_rules`만 있고 `evidence`가 비면 검산에서 걸린다.
