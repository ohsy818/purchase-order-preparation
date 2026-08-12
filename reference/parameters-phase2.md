# 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `approval_rules` | 객체 배열 | `[]` | 승인이 필요한 조건. **비면 승인 판정을 하지 않는다** |
| `rounding_policy` | 문자열 | `"moq_then_pack"` | 수량 올림 순서. `moq_then_pack` / `pack_then_moq` / `none` |
| `group_by_vendor` | boolean | `true` | 같은 공급처 품목을 한 문서로 묶을지 |
| `split_urgent` | boolean | `false` | 긴급 품목을 별도 문서로 분리할지 |
| `buffer_days` | 정수 | `0` | 납기 희망일 산정 시 여유일 |
| `order_date` | 날짜 | 오늘 | 납기 산정의 기준일 |
| `draft_state` | 문자열 | `"draft"` | 생성할 문서의 상태 문자열 |
| `allow_confirm` | boolean | `false` | **항상 false.** true를 주면 스크립트가 거부한다 |
| `vendor_terms` | 객체 | `{}` | 공급처별 무료배송·최소주문금액 기준 |
| `doc_prefix` | 문자열 | `"DRAFT"` | 생성 문서번호 접두어 |

## params.json 예

```json
{
  "approval_rules": [],
  "rounding_policy": "moq_then_pack",
  "group_by_vendor": true,
  "split_urgent": false,
  "buffer_days": 0,
  "draft_state": "draft",
  "vendor_terms": {},
  "doc_prefix": "DRAFT"
}
```

## 파라미터를 정할 때 생각할 것

**`approval_rules`**
이 스킬에서 가장 중요한 파라미터다. 형식과 작성법은 `approval-rules.md`.
비워 두면 승인 판정이 아예 안 나오고 「정책 미설정」으로 보고된다.
**이것이 의도된 동작이다.** 규칙을 못 받았는데 스킬이 알아서 판정하면,
조직이 정하지 않은 기준으로 결재가 갈리게 된다.

**`rounding_policy`**
`moq_then_pack`이 기본이다. MOQ를 먼저 맞추고, 그 값을 포장 배수로 올린다.
`pack_then_moq`는 포장 배수로 먼저 올린 뒤 MOQ 미달이면 다시 올린다.
대부분 결과가 같지만, MOQ가 포장 배수가 아닐 때 달라진다.
어느 쪽이든 조직 관행에 맞춰 **한 번 정하고 바꾸지 않는다.**

`none`은 소요량 그대로 주문한다. MOQ·포장 개념이 없는 서비스 발주에 쓴다.

**`split_urgent`**
긴급 건이 장납기 건에 묶여 함께 늦어지는 것을 막는다.
공급처가 분할 배송을 안 받아 주면 켜 봐야 의미가 없다.
배송비가 건당 붙는다면 비용이 늘어난다.

**`buffer_days`**
공급처 납기 준수율이 낮으면 올린다.
다만 여유일을 늘리면 재고가 늘어난다. 지연 실적을 보고 정한다.

**`allow_confirm`**
설정 자리는 있지만 `true`를 넣으면 스크립트가 오류를 낸다.
"나중에 자동 확정 기능을 켤 수 있다"는 착각을 막기 위해 자리만 두고 잠가 놓았다.
확정은 사람이 한다.

**`vendor_terms`**
```json
{"공급처명": {"free_shipping_over": 50000, "min_order_amount": 100000}}
```
스킬은 이 값으로 **메모를 남길 뿐 수량을 바꾸지 않는다.**
