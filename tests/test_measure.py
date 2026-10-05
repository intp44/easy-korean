"""측정 스크립트 (measure.py) — 문장 세는 기준, 정확도 비교 범위. AI를 부르지 않습니다. 모든 값은 가짜입니다."""

from measure import avg_len, easy_part, score, sentences

FAKE_RESULT = """[해야 할 일]
- 언제까지: 2026. 11. 4.
- 어디로: 가상은행 562-000-81234567
- 얼마를: 32,000원

[쉬운 설명]
박○○ 님의 차가 2026. 10. 7.에 잘못 서 있었습니다.
과태료(법을 어겨서 내는 돈)를 내야 합니다.

2026. 11. 4.까지 내면 32,000원만 내요.
고지번호: 2026-1011-004512
구분 | 금액
- 신분증을 가져가세요.
궁금하면 가상구청에
물어보세요.
정말 안 내면 어떻게 되나요?
- 계좌 번호

[어려운 말 풀이]
- 과태료: 법을 어겨서 내는 돈"""


def test_result_sentences_same_rules():
    assert sentences(easy_part(FAKE_RESULT)) == [
        "박○○ 님의 차가 2026. 10. 7.에 잘못 서 있었습니다.",     # 날짜 속 점에서 자르지 않음
        "과태료(법을 어겨서 내는 돈)를 내야 합니다.",
        "2026. 11. 4.까지 내면 32,000원만 내요.",
        "신분증을 가져가세요.",                                   # 목록 기호는 빼고 셈
        "궁금하면 가상구청에 물어보세요.",                         # 줄바꿈으로 끊긴 문장은 이어 붙임
        "정말 안 내면 어떻게 되나요?",
    ]                                                             # 이름표 줄, 표 칸, 끝맺지 않은 조각은 셈에서 빠짐


def test_original_sentences_same_rules():
    original = """가상시 가상구
수신자: 박가상 귀하
「도로교통법」 제32조에 따라 2026. 11. 4.(수)까지
의견제출서를 제출하여 주시기 바랍니다.
자진납부 기한: 2026. 11. 4.(수)
본래 과태료 | 40,000
1. 진단서 원본 1부 (최근 3개월 이내 발급분)
※ 대리인이 오는 경우에는 위임장을 가져오십시오. 문의는 055-000-3101"""
    assert sentences(original) == [
        "「도로교통법」 제32조에 따라 2026. 11. 4.(수)까지 의견제출서를 제출하여 주시기 바랍니다.",
        "대리인이 오는 경우에는 위임장을 가져오십시오.",
    ]


def test_sentence_length_ignores_spaces():
    # "가 나 다." → 4자, "라마 바사합니다." → 8자 (마침표 포함, 띄어쓰기 제외)
    assert avg_len("가 나 다.\n라마 바사합니다.") == (4 + 8) / 2


def test_no_real_sentence_gives_none():
    assert avg_len("고지번호: 2026-0001\n합계 | 52,510\n납부기한: 2026. 11. 30.") is None


def test_time_with_colon_is_still_a_sentence():
    assert sentences("검사 시간 08:30까지 오세요.") == ["검사 시간 08:30까지 오세요."]


def test_checklist_found_anywhere_others_only_in_todo():
    answer = {"기한": "2026. 11. 4.", "장소": "가상은행 562-000-81234567", "금액": "32,000;99,000", "준비물": "신분증;위임장"}
    hit, total, misses, by_field = score(answer, FAKE_RESULT)
    assert by_field == {"기한": (1, 1), "장소": (1, 1), "금액": (1, 2), "준비물": (1, 2)}
    assert (hit, total) == (4, 6) and misses == ["금액:99,000", "준비물:위임장"]


def test_value_only_outside_todo_is_a_miss_except_checklist():
    # 2026. 10. 7.은 [쉬운 설명]에만 있으므로 기한으로는 틀림, 신분증은 준비물이라 결과 전체에서 찾아 맞음
    hit, total, misses, _ = score({"기한": "2026. 10. 7.", "준비물": "신분증"}, FAKE_RESULT)
    assert misses == ["기한:2026. 10. 7."] and hit == 1
