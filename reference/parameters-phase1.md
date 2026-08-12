# 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|---|---|---|---|
| `long_lead_days` | 정수 \| null | `null` | 리드타임이 이 값 이상이면 「장납기」 표시. null이면 표시하지 않음 |
| `lead_time_basis` | 문자열 | `"max"` | 리드타임이 범위일 때 `max` / `min` / `mid` 중 무엇을 쓸지 |
| `safety_buffer_days` | 정수 | `0` | 주문 마감일 역산 시 확보할 여유일 |
| `category_scheme` | 문자열 배열 | `[]` | 신규 품목을 붙일 카테고리 목록. 비면 카테고리 미지정으로 초안 생성 |
| `tax_convention` | 문자열 | `"unspecified"` | `included` / `excluded` / `unspecified`. 단가의 부가세 처리 표기 |
| `base_currency` | 문자열 \| null | `null` | 표기 기준 통화. **환산은 하지 않는다** |
| `auto_create_draft` | boolean | `true` | 미등록 품목의 초안을 생성할지, 목록만 낼지 |
| `required_terms` | 문자열 배열 | `["unit_price","lead_time_days","moq"]` | 이 중 하나라도 없으면 「조건 미비」 |

## params.json 예

```json
{
  "long_lead_days": null,
  "lead_time_basis": "max",
  "safety_buffer_days": 0,
  "category_scheme": [],
  "tax_convention": "unspecified",
  "base_currency": null,
  "auto_create_draft": true,
  "required_terms": ["unit_price", "lead_time_days", "moq"]
}
```

## 파라미터를 정할 때 생각할 것

**`lead_time_basis`**
`max`가 기본이다. "5~7일"을 5일로 잡으면 납기 계획이 늘 늦는다.
`min`은 공급처가 낙관치를 적는 관행이 없고 실적이 안정적일 때만 쓴다.
어느 쪽을 쓰든 **범위 원문을 표에 함께 남긴다.**

**`long_lead_days`**
"이 리드타임이면 미리 계획해야 한다"의 경계다.
점검 주기와 연결해서 정한다. 주 1회 점검인데 기준을 30일로 잡으면
장납기 품목이 매번 늦게 잡힌다. 보통 점검 주기의 2배 이상으로 둔다.

**`required_terms`**
여기 넣은 항목이 없으면 그 품목은 주문서로 넘어가지 못한다.
포장 단위(`pack_size`)를 넣을지가 판단 지점이다.
넣으면 조건 미비가 늘고, 빼면 주문서 작성 단계에서 올림을 못 한다.

**`base_currency`**
표기 기준일 뿐이다. **이 스킬은 환산하지 않는다.**
환율은 시점에 따라 달라져서, 비교표에 환산값을 넣으면
언제 기준인지 모르는 숫자가 남는다. 원 통화로 보여 주고 판단은 사람이 한다.

**`tax_convention`**
`unspecified`로 두면 스크립트가 모든 단가에 「부가세 확인 필요」를 붙인다.
불편하지만 옳다. 부가세 포함 여부를 모르는 단가로 금액을 계산하면 10% 틀린다.
