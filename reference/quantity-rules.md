# 수량·납기 계산 규칙

`scripts/draft_orders.py`가 구현하는 규칙이다.
스크립트를 쓸 수 없는 환경에서는 이 문서를 그대로 따른다.

## 1. 묶음

```
group_by_vendor = true  →  같은 공급처 품목을 한 문서로
split_urgent    = true  →  긴급 품목은 별도 문서로 분리
공급처 미선택            →  묶지 않고 보류 (held)
```

복수 공급처 품목인데 `vendor_selection`이 없으면 **임의로 고르지 않는다.**
단독 공급처면 선택 없이 그 공급처로 진행한다.

## 2. 주문수량 올림

```
기본 수량 = 순소요량

rounding_policy = moq_then_pack
  1) 수량 < MOQ 이면  수량 = MOQ
  2) pack_size 가 있으면  수량 = ceil(수량 / pack_size) × pack_size

rounding_policy = pack_then_moq
  1) pack_size 가 있으면  수량 = ceil(수량 / pack_size) × pack_size
  2) 수량 < MOQ 이면      수량 = ceil(MOQ / pack_size) × pack_size

rounding_policy = none
  수량 = 순소요량
```

**올림 사유를 반드시 기록한다.**

| 사유 코드 | 뜻 |
|---|---|
| `moq` | MOQ 미달로 올림 |
| `pack` | 포장 단위 배수로 올림 |
| `moq+pack` | 둘 다 적용 |
| `none` | 올림 없음 |

### 목표재고 초과

```
주문수량 + 현재고 > 목표재고  →  「목표재고 초과」 표시
```

**수량은 유지한다. 임의로 줄이지 않는다.** MOQ 때문에 넘치는 것은 불가피하다.
줄이면 MOQ 미달로 주문 자체가 거절된다.

## 3. 금액

```
금액 = 단가 × 주문수량
```

수량 구간별 단가가 있으면 **확정된 주문수량이 속한 구간의 단가**를 쓴다.
구간 선택 근거를 기록한다.

부가세 처리는 공급 조건의 `tax` 값을 따른다. 불명이면 「부가세 확인 필요」를 남기고
금액을 계산하되 그 사실을 표시한다.

## 4. 거래 조건 반영

```
합계 금액 ≥ free_shipping_over          →  「무료배송 적용」
합계 금액 < free_shipping_over 의 90%   →  아무것도 하지 않음
free_shipping_over 의 90% ≤ 합계 < 기준 →  「무료배송 기준 근접」 메모
합계 금액 < min_order_amount            →  「최소 주문 금액 미달」 표시
```

**어느 경우에도 수량을 늘리지 않는다.** 사실만 남긴다.
"조금만 더 사면 배송비가 무료"라는 판단은 사람이 한다.

## 5. 납기 희망일

```
납기 희망일 = order_date + 리드타임 + buffer_days
```

리드타임은 `supply_options`에서 받은 확정값을 쓴다. 다시 계산하지 않는다.

```
need_by 가 있고  납기 희망일 > need_by  →  「납기 부족」 표시
```

**「납기 부족」이어도 초안은 만든다.** 대체품을 찾거나 수량을 나누는 판단이
필요한 건이라는 신호이지, 주문하지 말라는 뜻이 아니다.

## 6. 문서 분류

```
1) 공급처 미선택 / 단가 결측 / MOQ 결측  →  held  (문서를 만들지 않는다)
2) approval_rules 가 비어 있음            →  ready_to_confirm + 「정책 미설정」
3) 규칙 1개 이상 해당                      →  approval_required
4) 그 외                                   →  ready_to_confirm
```

## 검산

| 항목 | 성립해야 하는 식 |
|---|---|
| 품목 보존 | 주문서에 들어간 품목 + `held_items` = 입력 품목 수 |
| 수량 하한 | 모든 주문수량 ≥ 순소요량 (올림만 하고 줄이지 않는다) |
| MOQ 충족 | 주문수량 ≥ MOQ |
| 포장 배수 | `pack_size`가 있으면 주문수량 % `pack_size` == 0 |
| 상태 | 모든 문서의 상태 == `draft_state` |
| 확정 금지 | 확정 관련 필드·플래그가 출력에 없음 |
| 근거 존재 | `approval_required`인 문서마다 해당 규칙과 근거가 있음 |
| 플래그 일치 | `requires_approval` == (`approval_required` 문서 > 0) |

`scripts/draft_orders.py`는 이 검산을 실행하고, 하나라도 어긋나면 오류를 낸다.
「수량 하한」과 「확정 금지」가 가장 중요한 두 검산이다.
