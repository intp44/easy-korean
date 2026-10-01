"""원문 대조 검증 (verify.py)

- 정방향: 원문의 중요 정보가 결과에 빠졌는지
- 역방향: 결과의 값이 원문에 실제로 있는지 (AI가 계산하거나 지어낸 값)
- 모양 맞추기: 모양이 달라도 같은 값이면 같은 것으로 보는지, 표 금액을 알아보는지
"""

import pytest

from verify import check, date_in_original, extract, invented_report, missing_report, number_digits

FINE_NOTICE = """과태료 부과 사전통지서
고지번호: 2026-0912-000123
전자납부번호: 0123-1-26090012345
2026. 9. 12. 주정차 위반으로 과태료 120,000원을 부과할 예정입니다.
2026. 10. 20.까지 자진납부 시 96,000원을 납부하시면 됩니다.
납부 가상계좌: 가상은행 110-987-654321
담당자: 이가상 주무관 (051-000-1234)"""

GOOD_RESULT = """- 언제까지: 2026. 10. 20.
- 어디로: 가상은행 110-987-654321
- 얼마를: 96,000원 (원래 120,000원)
- 고지번호: 2026-0912-000123
- 전자납부번호: 0123-1-26090012345
2026. 9. 12.에 차를 잘못 세웠습니다. 궁금하면 051-000-1234로 연락하세요."""


def values(items):
    return [item.value for item in items]


# ── 정방향: 빠진 정보 ─────────────────────────────────
def test_complete_result_has_nothing_missing():
    result = check(FINE_NOTICE, GOOD_RESULT)
    assert result.ok and result.all_ok
    assert result.missing == [] and result.invented == []


def test_missing_date():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("2026. 10. 20.", "기한 안에"))
    assert values(result.missing) == ["2026. 10. 20."]


def test_missing_amount():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("96,000원", "깎인 돈"))
    assert values(result.missing) == ["96,000원"]


def test_missing_phone():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("051-000-1234", "담당자"))
    assert values(result.missing) == ["051-000-1234"]


def test_missing_account():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("110-987-654321", "가상계좌"))
    assert values(result.missing) == ["110-987-654321"]


def test_missing_labeled_number():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("- 전자납부번호: 0123-1-26090012345\n", ""))
    assert [(i.kind, i.value) for i in result.missing] == [("전자납부번호", "0123-1-26090012345")]


def test_missing_report_text():
    result = check(FINE_NOTICE, GOOD_RESULT.replace("051-000-1234", "담당자"))
    assert missing_report(result) == "[확인 필요] 원문에 있는데 결과에 빠진 정보\n- 전화번호: 051-000-1234"


def test_masked_values_are_not_checked():
    original = "연락처: 010-****-****\n환급계좌: 가상은행 352-****-****-**\n수신자 김○○"
    assert extract(original) == []


def test_document_number_law_and_page_are_not_checked():
    original = "문서번호: 교통행정과-12345\n도로교통법 제32조 제3항에 따라\n- 1 -\n1/3쪽"
    assert extract(original) == []


def test_date_without_year_found_with_year_in_result():
    result = check("10월 20일까지 제출", "2026년 10월 20일까지 내세요.")
    assert result.missing == []


# ── 역방향: 원문에 없는 값 ────────────────────────────
def test_calculated_amount_is_invented():
    # 120,000 - 96,000 = 24,000 : 원문에 없는 계산 값
    result = check(FINE_NOTICE, GOOD_RESULT + "\n24,000원을 아낄 수 있어요.")
    assert values(result.invented) == ["24,000원"]


def test_period_turned_into_date_is_invented():
    result = check("통지를 받은 날부터 14일 이내에 제출", "2026. 10. 15.까지 내세요.")
    assert values(result.invented) == ["2026. 10. 15."]


def test_invented_phone():
    result = check(FINE_NOTICE, GOOD_RESULT + "\n고객센터 1588-9999")
    assert values(result.invented) == ["1588-9999"]


def test_invented_account():
    result = check(FINE_NOTICE, GOOD_RESULT + "\n가상은행 110-111-222333")
    assert values(result.invented) == ["110-111-222333"]


def test_wrong_year_is_invented():
    result = check("2026. 10. 20.까지", "2027. 10. 20.까지")
    assert values(result.invented) == ["2027. 10. 20."]


def test_year_added_passes_but_is_recorded():
    result = check("10월 20일까지 제출", "2026년 10월 20일까지 내세요.")
    assert result.invented == []
    assert values(result.year_added) == ["2026년 10월 20일"]


def test_year_added_for_date_shape_not_extracted_in_original():
    # 원문의 "10. 20." 모양은 중요 정보로 뽑히지 않지만 같은 월·일로 보고 통과합니다.
    result = check("마감 10. 20. 까지", "2026년 10월 20일까지")
    assert result.invented == [] and values(result.year_added) == ["2026년 10월 20일"]


def test_explanation_section_is_also_checked():
    result = check(FINE_NOTICE, GOOD_RESULT + "\n[어려운 말 풀이]\n- 과태료: 보통 50,000원 정도 내는 돈")
    assert values(result.invented) == ["50,000원"]


def test_value_in_original_is_not_invented():
    result = check(FINE_NOTICE, "2026. 9. 12. 위반, 120,000원")
    assert result.invented == []


def test_invented_report_text():
    result = check(FINE_NOTICE, GOOD_RESULT + "\n고객센터 1588-9999")
    assert invented_report(result).endswith("- 전화번호: 1588-9999")
    assert not result.all_ok and result.ok


def test_no_problems_means_empty_reports():
    result = check(FINE_NOTICE, GOOD_RESULT)
    assert missing_report(result) == "" and invented_report(result) == ""


def test_same_number_different_label_in_result_is_ok():
    # 원문에서 고객번호인 번호를 결과가 그냥 숫자로 적어도 원문에 있는 값입니다.
    result = check("고객번호: 010-4567-8910", "고객번호는 01045678910입니다.")
    assert result.all_ok


# ── 모양 맞추기 ───────────────────────────────────────
@pytest.mark.parametrize("original, result_text", [
    ("과태료 120,000원", "12만 원"),
    ("과태료 120,000원", "120000원"),
    ("보증금 1억 2,000만 원", "120,000,000원"),
    ("2026년 10월 16일", "2026. 10. 16."),
    ("2026. 10. 16.", "10월 16일"),
    ("26.10.16까지", "2026년 10월 16일까지"),         # 두 자리 연도
    ("문의 (055) 000-1111", "055-000-1111"),         # 괄호 전화번호
    ("2026/10/16", "2026-10-16"),
])
def test_same_value_different_shape(original, result_text):
    result = check(original, result_text)
    assert result.all_ok, (result.missing, result.invented)


def test_labeled_amount_without_won():
    assert values(extract("납부금액 96,000")) == ["96,000"]


def test_table_amount_column():
    original = "항목 | 금액(원)\n기본요금 | 1,000\n사용요금 | 44,320\n합계 | 45,320"
    assert sorted(i.key[1] for i in extract(original)) == [1000, 44320, 45320]


def test_table_unit_won_skips_count_column():
    original = "(단위: 원)\n구분 | 사용량 | 요금\n9월 | 32 | 45,320"
    assert [i.key for i in extract(original)] == [("금액", 45320)]


def test_number_with_unit_is_not_money():
    assert extract("사용량 32㎥, 인원 3명, 할인 20%") == []


# ── 다른 단계에서 쓰는 도구 ───────────────────────────
def test_date_in_original():
    assert date_in_original(FINE_NOTICE, 2026, 10, 20) == (True, 2026)
    assert date_in_original(FINE_NOTICE, 2026, 10, 21) == (False, None)
    assert date_in_original("10월 20일까지", 2026, 10, 20) == (True, None)
    assert date_in_original("2025. 10. 20.", 2026, 10, 20) == (False, None)


def test_number_digits():
    assert {"0510001234", "0550001111"} <= number_digits("051-000-1234, (055) 000-1111")
