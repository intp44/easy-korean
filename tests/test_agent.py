"""도움 고르기 (agent.py) — 가짜 AI 응답으로 코드 확인 부분만 시험합니다."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from agent import DEFAULT_INQUIRY, INQUIRY_END, INQUIRY_START, MODEL, HelpError, choose_help, full_inquiry, make_ics
from fakes import FakeClient, text_block, tool_block

TODAY = date(2026, 10, 1)

FINE_NOTICE = """과태료 부과 사전통지서
고지번호: 2026-0912-000123
수신자 김○○ 귀하
2026. 9. 12. 주정차 위반으로 과태료 120,000원을 부과할 예정입니다.
2026. 10. 20.까지 자진납부 시 96,000원을 납부하시면 됩니다.
납부 가상계좌: 가상은행 110-987-654321
담당자: 교통행정과 이가상 주무관 (051-000-1234)"""

VISIT_GUIDE = """장애인 복지카드 재발급 안내
신청 기간: 10. 1. ~ 10월 30일
준비물: 신분증, 최근 6개월 이내 사진 1매
문의: 가상시청 장애인복지과 055-000-2345"""


def run(blocks, original=FINE_NOTICE, stop_reason="tool_use"):
    client = FakeClient(blocks=blocks, stop_reason=stop_reason)
    return choose_help(client, original, "쉬운 결과", today=TODAY), client


# ── AI에게 보내는 내용 ────────────────────────────────
def test_sends_masked_text_and_tools_once():
    _, client = run([])
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == MODEL == "claude-haiku-4-5"
    assert {tool["name"] for tool in call["tools"]} == {"make_schedule", "draft_inquiry", "make_checklist"}
    assert "<원문>\n" + FINE_NOTICE in call["messages"][0]["content"]


def test_no_tool_means_empty_plan():
    plan, _ = run([text_block("없음")], "신분증 재발급 신청서 양식입니다.", stop_reason="end_turn")
    assert plan.empty


def test_refusal_raises():
    with pytest.raises(HelpError):
        run([], stop_reason="refusal")


# ── 일정: 원문에 없는 날짜 거르기 ─────────────────────
def test_schedule_with_date_in_original():
    plan, _ = run([tool_block("make_schedule", {"date": "2026-10-20", "title": "과태료 납부 기한"})])
    assert plan.schedule.day == date(2026, 10, 20)
    assert plan.schedule.label == "10월 20일"
    assert plan.dropped == []


def test_schedule_with_date_not_in_original_is_dropped():
    plan, _ = run([tool_block("make_schedule", {"date": "2026-10-26", "title": "14일 뒤"})])
    assert plan.schedule is None
    assert plan.dropped == ["일정: 원문에 없는 날짜 (2026-10-26)"]


def test_schedule_with_bad_date_shape_is_dropped():
    plan, _ = run([tool_block("make_schedule", {"date": "10월 20일", "title": "기한"})])
    assert plan.schedule is None and "날짜 모양이 이상함" in plan.dropped[0]


def test_schedule_without_year_uses_nearest_future_day():
    plan, _ = run([tool_block("make_schedule", {"date": "2025-10-30", "title": "신청 마감"})], VISIT_GUIDE)
    assert plan.schedule.day == date(2026, 10, 30)
    plan, _ = run([tool_block("make_schedule", {"date": "2026-09-30", "title": "지난 날"})],
                  "9월 30일까지 제출")
    assert plan.schedule.day == date(2027, 9, 30)


def test_only_first_schedule_is_used():
    plan, _ = run([
        tool_block("make_schedule", {"date": "2026-10-20", "title": "첫째"}),
        tool_block("make_schedule", {"date": "2026-09-12", "title": "둘째"}),
    ])
    assert plan.schedule.title == "첫째"


# ── 문의 문장: 원문에 없는 전화번호 거르기 ─────────────
def test_inquiry_keeps_phone_in_original():
    plan, _ = run([tool_block("draft_inquiry", {"message": "과태료 문의입니다. 051-000-1234로 답 주세요."})])
    assert "051-000-1234" in plan.inquiry and plan.dropped == []


def test_inquiry_replaces_invented_phone():
    plan, _ = run([tool_block("draft_inquiry", {"message": "문의: 02-111-2222로 연락 부탁드립니다."})])
    assert "02-111-2222" not in plan.inquiry and "[연락처]" in plan.inquiry
    assert plan.dropped == ["문의 문장: 원문에 없는 전화번호를 뺌 (02-111-2222)"]


def test_inquiry_removes_invented_phone_joined_to_real_one():
    plan, _ = run([tool_block("draft_inquiry", {"message": "051-000-1234 / 010-9999-8888로 연락 주세요."})])
    assert "051-000-1234" in plan.inquiry and "010-9999-8888" not in plan.inquiry and "/" not in plan.inquiry


def test_inquiry_removes_invented_phone_in_brackets():
    plan, _ = run([tool_block("draft_inquiry", {"message": "(051) 999-8888 또는 051-000-1234로 문의합니다."})])
    assert "999-8888" not in plan.inquiry and "또는" not in plan.inquiry and "051-000-1234" in plan.inquiry


# ── 준비물: 원문에 없는 것 거르기 ─────────────────────
def test_checklist_keeps_items_in_original():
    plan, _ = run([tool_block("make_checklist", {"items": ["신분증", "최근 6개월 이내 사진 1매"]})], VISIT_GUIDE)
    assert plan.checklist == ["신분증", "최근 6개월 이내 사진 1매"]


def test_checklist_drops_item_not_in_original():
    plan, _ = run([tool_block("make_checklist", {"items": ["신분증", "도장", "신분증"]})], VISIT_GUIDE)
    assert plan.checklist == ["신분증"]
    assert plan.dropped == ["준비물: 원문에 없는 것 같아 뺌 (도장)"]


# ── 일정 파일 (.ics) 형식 ─────────────────────────────
def ics():
    return make_ics(date(2026, 10, 20), "과태료, 납부; 기한", now=datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc))


def test_ics_basic_shape():
    text = ics()
    lines = text.split("\r\n")
    assert lines[0] == "BEGIN:VCALENDAR" and text.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261020" in lines
    assert "DTEND;VALUE=DATE:20261021" in lines
    assert "DTSTAMP:20261001T000000Z" in lines
    assert "\n" not in text.replace("\r\n", "")   # 줄바꿈은 모두 \r\n


def test_ics_escapes_special_characters():
    assert "SUMMARY:과태료\\, 납부\\; 기한" in ics().split("\r\n")


def test_ics_has_two_alarms():
    text = ics()
    assert text.count("BEGIN:VALARM") == 2
    assert "TRIGGER:-PT15H" in text and "TRIGGER:-P2DT15H" in text


def test_ics_long_lines_are_folded_under_75_bytes():
    text = make_ics(date(2026, 10, 20), "아주 긴 일정 제목입니다 " * 5)
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75
    assert "\r\n " in text   # 이어지는 줄은 띄어쓰기로 시작


def test_ics_month_end_next_day():
    assert "DTEND;VALUE=DATE:20270101" in make_ics(date(2026, 12, 31), "연말")


MIXED = """건강보험료 정산 결과 안내
가. 추가 납부
  - 추가 납부 금액: 84,200원
  - 납부 기한: 2026. 11. 10.
  - 납부 가상계좌: 가상은행 1002-876-543210
  - 전자납부번호: 0987-6-26110045678
문의: 가상건강보험공단 고객센터 1577-0000"""


# ── 문제 1. 준비물에 돈 내기 방법·번호가 들어감 ───────
def test_checklist_drops_payment_steps_from_fine_notice():
    plan, _ = run([tool_block("make_checklist", {"items": [
        "과태료 96,000원 준비", "가상은행 계좌 110-987-654321로 납부", "전자납부번호 0123-1-26090012345 사용",
    ]})])
    assert plan.checklist == []
    assert len(plan.dropped) == 3 and all("준비물이 아니라서" in d for d in plan.dropped)


def test_checklist_drops_payment_steps_from_mixed_notice():
    plan, _ = run([tool_block("make_checklist", {"items": [
        "가상은행 1002-876-543210 (가상계좌)로 84,200원 납부", "전자납부번호: 0987-6-26110045678", "고지번호",
    ]})], MIXED)
    assert plan.checklist == []


def test_checklist_drops_payment_words_without_numbers():
    plan, _ = run([tool_block("make_checklist", {"items": ["가상은행 계좌로 납부", "가상계좌 입금"]})])
    assert plan.checklist == []


def test_checklist_keeps_short_quantities():
    # "6개월", "1매"는 금액·번호가 아니라 준비물 설명입니다.
    plan, _ = run([tool_block("make_checklist", {"items": ["최근 6개월 이내 사진 1매"]})], VISIT_GUIDE)
    assert plan.checklist == ["최근 6개월 이내 사진 1매"]


def test_checklist_keeps_reordered_item():
    plan, _ = run([tool_block("make_checklist", {"items": ["사진 1매 (최근 6개월 이내)"]})], VISIT_GUIDE)
    assert plan.checklist == ["사진 1매 (최근 6개월 이내)"]


def test_checklist_drops_item_only_loosely_related():
    # 예전 기준(두 글자만 겹치면 통과)에서는 '신분증 사본'이 통과했지만, 이제는 원문에 거의 그대로 있어야 합니다.
    plan, _ = run([tool_block("make_checklist", {"items": ["신분증 사본", "주민등록등본"]})], VISIT_GUIDE)
    assert plan.checklist == []


# ── 문제 2. 문의 문장 모양 ─────────────────────────────
def test_inquiry_always_has_fixed_start_and_end():
    plan, _ = run([tool_block("draft_inquiry", {"message": "고지번호 2026-0912-000123 과태료에 대해 묻고 싶습니다."})])
    assert plan.inquiry == (
        "안녕하세요. [이름]입니다.\n"
        "고지번호 2026-0912-000123 과태료에 대해 묻고 싶습니다.\n"
        "저는 청각장애가 있어 전화 통화가 어렵습니다. 문자로 답변 부탁드립니다. 감사합니다."
    )


def test_inquiry_removes_sentences_ai_should_not_write():
    message = ("안녕하세요. [이름]입니다. 과태료 납부 방법을 알고 싶습니다. "
               "저는 청각장애가 있어 전화 통화가 어렵습니다. 문자로 답해 주시면 감사하겠습니다.")
    plan, _ = run([tool_block("draft_inquiry", {"message": message})])
    assert plan.inquiry == full_inquiry("과태료 납부 방법을 알고 싶습니다.")
    assert plan.inquiry.count("[이름]") == 1 and plan.inquiry.count("청각장애") == 1


def test_inquiry_with_only_repeated_sentences_uses_default_body():
    plan, _ = run([tool_block("draft_inquiry", {"message": "안녕하세요. 감사합니다."})])
    assert plan.inquiry == full_inquiry(DEFAULT_INQUIRY)


def test_inquiry_body_on_separate_lines_is_joined():
    plan, _ = run([tool_block("draft_inquiry", {"message": "과태료 문의입니다.\n감경 기준을 알려 주세요."})])
    assert plan.inquiry.split("\n")[1] == "과태료 문의입니다. 감경 기준을 알려 주세요."


def test_screen_hint_matches_inquiry():
    # 화면 안내 "[이름]은 내 이름으로 바꿔 주세요"는 문의 문장에 [이름]이 늘 있어야 맞습니다.
    app_text = (Path(__file__).resolve().parent.parent / "app.py").read_text(encoding="utf-8")
    assert "[이름]은 내 이름으로 바꿔 주세요" in app_text
    assert "[이름]" in INQUIRY_START and "[이름]" not in INQUIRY_END


# ── 문제 3. 연락처가 있어도 문의 도구를 안 고름 ───────
def test_code_adds_inquiry_when_contact_phone_exists():
    plan, _ = run([tool_block("make_schedule", {"date": "2026-11-10", "title": "건강보험료 추가 납부"})], MIXED)
    assert plan.inquiry == full_inquiry(DEFAULT_INQUIRY)
    assert plan.added == ["문의 문장: 원문에 문의 번호가 있어 기본 문장을 더함 (1577-0000)"]


def test_code_does_not_replace_inquiry_ai_wrote():
    plan, _ = run([tool_block("draft_inquiry", {"message": "추가 납부 금액이 왜 생겼는지 알고 싶습니다."})], MIXED)
    assert "왜 생겼는지" in plan.inquiry and plan.added == []


def test_contact_labels():
    for original in ("고객센터: 1588-0000 (가상도시가스)", "담당자: 교통행정과 이가상 주무관 (051-000-1234)",
                     "수어 영상상담 070-0000-1111", "문의: 가상구청 세무1과 환급담당 (032-000-5678)"):
        plan, _ = run([], original)
        assert plan.inquiry == full_inquiry(DEFAULT_INQUIRY), original


def test_no_inquiry_without_labeled_contact_phone():
    for original in ("연락처: 010-****-****",            # 가려진 개인 번호
                     "가상구청 051-000-1234",             # 이름표 없는 번호
                     "051-000-1234 문의",                 # 이름표가 번호 뒤에 있음
                     "문의 사항은 홈페이지에 남겨 주세요."):  # 번호 없음
        plan, _ = run([], original)
        assert plan.inquiry is None, original


# ── 문제 4. 지시문에 새 규칙이 들어갔는지 (AI에게 실제로 보내는 도구 설명) ──
def test_prompt_rules_reach_ai():
    _, client = run([])
    tools = {tool["name"]: tool["description"] for tool in client.calls[0]["tools"]}
    assert "조건을 함께 씁니다" in tools["make_schedule"]
    assert "조건 없는 기한이 따로 있으면 그것을 우선합니다" in tools["make_schedule"]
    assert "준비물이 아닙니다" in tools["make_checklist"]
    assert "이 도구를 꼭 고릅니다" in tools["draft_inquiry"]
    assert "쓰지 않습니다" in tools["draft_inquiry"]


# ── 조건이 붙은 기한 ──────────────────────────────────
REFUND = """지방세 과오납금 환급 안내
4. 환급 예정일: 2026. 10. 15.

환급계좌가 변경되었거나 잘못된 경우 2026. 10. 8.까지 아래로 연락하여 주시기 바랍니다.
문의: 가상구청 세무1과 (032-000-5678)"""


def schedule_for(original, day, title):
    plan, _ = run([tool_block("make_schedule", {"date": day, "title": title})], original)
    return plan.schedule


def test_conditional_deadline_gets_note():
    schedule = schedule_for(REFUND, "2026-10-08", "환급계좌 변경 확인 기한")
    assert schedule.conditional
    assert schedule.title == "환급계좌 변경 확인 기한 (해당하는 경우만)"
    assert schedule.label == "10월 8일, 해당하는 경우만"           # 화면 버튼 글자
    assert "SUMMARY:환급계좌 변경 확인 기한 (해당하는 경우만)" in schedule.ics.split("\r\n")   # 일정 파일 제목


def test_unconditional_deadline_has_no_note():
    schedule = schedule_for(FINE_NOTICE, "2026-10-20", "과태료 납부 기한")
    assert not schedule.conditional
    assert schedule.title == "과태료 납부 기한" and schedule.label == "10월 20일"


def test_condition_word_in_other_sentence_does_not_count():
    original = ("2026. 10. 20.까지 과태료를 납부하시기 바랍니다. "
                "의견이 있는 경우 가상구청에 의견서를 제출할 수 있습니다.\n"
                "감면 해당자는 증빙 서류를 함께 내세요.")
    schedule = schedule_for(original, "2026-10-20", "과태료 납부 기한")
    assert not schedule.conditional and schedule.title == "과태료 납부 기한"


def test_title_already_has_condition():
    schedule = schedule_for(REFUND, "2026-10-08", "환급 계좌 변경 기한 (계좌가 틀린 경우만)")
    assert schedule.title == "환급 계좌 변경 기한 (계좌가 틀린 경우만)"
    assert schedule.title.count("경우만") == 1 and not schedule.conditional


def test_condition_words():
    for sentence in ("감면 해당자는 2026. 10. 30.까지 신청하세요.",
                     "지원을 원하는 해당하는 분은 10월 30일까지 신청하세요.",
                     "서류가 빠진 경우 2026-10-30까지 다시 제출합니다."):
        assert schedule_for(sentence, "2026-10-30", "신청 마감").conditional, sentence


def test_same_date_also_in_unconditional_sentence():
    # 같은 날짜가 조건 없는 문장에도 있으면 모두에게 해당하는 기한일 수 있으므로 붙이지 않습니다.
    original = "신청 기간: 2026. 10. 30.까지\n서류가 빠진 경우에도 2026. 10. 30.까지 다시 내세요."
    assert not schedule_for(original, "2026-10-30", "신청 마감").conditional


def test_date_dots_do_not_split_sentence():
    # '2026. 10. 8.'의 점에서 문장을 자르면 조건 말과 날짜가 떨어져 보입니다.
    original = "잘못된 경우 2026. 10. 8. 까지 연락하세요."
    assert schedule_for(original, "2026-10-08", "연락 기한").conditional
