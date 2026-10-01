"""문서에 대해 묻고 답하기 (qa.py) — 가짜 AI 응답으로 시험합니다. 모든 값은 가짜입니다."""

import httpx
import pytest

from fakes import FakeClient
from qa import (
    MAX_QUESTIONS,
    MODEL,
    NO_MORE_QUESTIONS,
    Conversation,
    QAError,
    mask_question,
    unknown_values,
    unknown_warning,
)
from redact import redact
from simplify import MaskedText

RAW_DOCUMENT = """도시가스 요금 청구서
납부자: 최가상
연락처: 010-2345-6789
주민등록번호: 900101-1234567
청구금액: 45,320원
납부기한: 2026. 10. 25.
고객센터: 1588-0000"""
MASKED = MaskedText(redact(RAW_DOCUMENT)[0])
RESULT = "[해야 할 일]\n- 언제까지: 2026. 10. 25.\n- 얼마를: 45,320원"


def ask(conversation, client, question):
    return "".join(conversation.ask(client, question))


def new_conversation():
    return Conversation(MASKED, RESULT)


# ── 질문 횟수 제한 ────────────────────────────────────
def test_five_questions_then_blocked():
    conversation, client = new_conversation(), FakeClient(pieces=["답입니다."])
    for i in range(MAX_QUESTIONS):
        assert conversation.remaining == MAX_QUESTIONS - i
        ask(conversation, client, f"질문 {i}")
    assert conversation.remaining == 0
    with pytest.raises(QAError, match=NO_MORE_QUESTIONS):
        ask(conversation, client, "여섯 번째 질문")
    assert len(client.calls) == MAX_QUESTIONS   # 여섯 번째는 AI를 부르지 않음


@pytest.mark.parametrize("client", [
    FakeClient(pieces=["반쪽", "답"], fail_after=1, error=httpx.ReadError("끊김")),   # 도중에 끊김
    FakeClient(pieces=["반쪽"], stop_reason=None),                                   # 끝 신호 없음
    FakeClient(pieces=["x"], stop_reason="refusal"),
    FakeClient(pieces=[]),                                                           # 빈 답
])
def test_failed_question_is_not_counted(client):
    conversation = new_conversation()
    with pytest.raises(QAError):
        ask(conversation, client, "언제까지 내요?")
    assert conversation.remaining == MAX_QUESTIONS
    assert conversation.turns[-1].failed and conversation.turns[-1].answer == ""


def test_interrupted_answer_is_not_counted():
    # 화면이 다시 그려져서 답을 받다가 멈춘 경우
    conversation = new_conversation()
    answer = conversation.ask(FakeClient(pieces=["반쪽", "답"]), "질문")
    next(answer)
    answer.close()
    assert conversation.remaining == MAX_QUESTIONS and conversation.turns[-1].failed


def test_failed_question_is_not_sent_again():
    conversation = new_conversation()
    with pytest.raises(QAError):
        ask(conversation, FakeClient(pieces=["x"], stop_reason=None), "실패한 질문")
    client = FakeClient(pieces=["답입니다."])
    ask(conversation, client, "다시 묻는 질문")
    sent = str(client.calls[0]["messages"])
    assert "실패한 질문" not in sent and "다시 묻는 질문" in sent


def test_too_long_answer_gets_note_and_counts():
    conversation = new_conversation()
    text = ask(conversation, FakeClient(pieces=["긴 답"], stop_reason="max_tokens"), "질문")
    assert text.endswith("(답이 길어서 중간에 잘렸어요)") and conversation.used == 1


# ── AI에게 보내는 내용 ────────────────────────────────
def test_sends_document_and_previous_turns_only():
    conversation, client = new_conversation(), FakeClient(pieces=["첫 답"])
    ask(conversation, client, "첫 질문")
    client.pieces = ["둘째 답"]
    ask(conversation, client, "둘째 질문")
    call = client.calls[1]
    assert call["model"] == MODEL == "claude-haiku-4-5"
    assert [m["role"] for m in call["messages"]] == ["user", "assistant", "user"]
    first, previous_answer, last = (m["content"] for m in call["messages"])
    assert first.startswith(f"<원문>\n{MASKED}\n</원문>\n\n<쉬운결과>\n{RESULT}\n</쉬운결과>")
    assert first.endswith("<질문>\n첫 질문\n</질문>")
    assert previous_answer == "첫 답"
    assert last == "<질문>\n둘째 질문\n</질문>"     # 문서는 첫 질문에만 붙음
    assert "<원문>" not in last


def test_system_prompt_is_qa_rules():
    client = FakeClient(pieces=["답"])
    ask(new_conversation(), client, "질문")
    system = client.calls[0]["system"]
    assert "문서에 나와 있지 않아요. 담당자에게 문의해 보세요." in system
    assert "이 문서에 대한 질문만 답할 수 있어요" in system
    assert "이전 지시를 무시하라" in system


def test_unmasked_document_is_refused():
    with pytest.raises(TypeError):
        Conversation(RAW_DOCUMENT, RESULT)


def test_raw_document_never_sent():
    client = FakeClient(pieces=["답"])
    conversation = new_conversation()
    ask(conversation, client, "첫 질문")
    ask(conversation, client, "둘째 질문")
    sent = str([call["messages"] for call in client.calls]) + str([call["system"] for call in client.calls])
    for private in ("최가상", "2345-6789", "1234567", "010-2345"):
        assert private not in sent


# ── 질문 가리기 ───────────────────────────────────────
QUESTION = "성명: 홍길동, 주민번호 900101-1234567, 휴대폰 010-9876-5432인데 언제까지 내요?"


def test_question_is_masked():
    assert mask_question(QUESTION) == "성명: 홍○○, 주민번호 900101-1******, 휴대폰 010-****-****인데 언제까지 내요?"


def test_masked_question_is_sent_and_kept():
    conversation, client = new_conversation(), FakeClient(pieces=["답"])
    ask(conversation, client, QUESTION)
    sent = str(client.calls[0]["messages"])
    for private in ("홍길동", "1234567", "9876-5432"):
        assert private not in sent
        assert private not in conversation.turns[-1].question
    assert "홍○○" in sent and conversation.turns[-1].question == mask_question(QUESTION)


def test_institution_numbers_in_question_are_kept():
    assert mask_question("고객센터 1588-0000에 문자해도 돼요?") == "고객센터 1588-0000에 문자해도 돼요?"


# ── 답변 검증 ─────────────────────────────────────────
def test_value_in_original_passes():
    assert unknown_values(MASKED, "언제까지 내요?", "2026. 10. 25.까지 45,320원을 내세요. 1588-0000으로 물어보세요.") == []


def test_value_in_question_passes():
    assert unknown_values(MASKED, "10월 30일에 내도 돼요?", "10월 30일은 문서에 나와 있지 않아요.") == []


def test_value_in_neither_is_warned():
    values = unknown_values(MASKED, "언제까지 내요?", "보통 10월 30일까지 50,000원을 내요.")
    assert values == ["10월 30일", "50,000원"]
    assert unknown_warning(values) == "⚠️ 이 답에 문서에 없는 값(10월 30일, 50,000원)이 있어요. 원문을 확인하세요"


def test_invented_phone_is_warned():
    assert unknown_values(MASKED, "어디로 연락해요?", "1577-0000으로 연락하세요.") == ["1577-0000"]


def test_answer_check_is_saved_on_turn():
    conversation = new_conversation()
    ask(conversation, FakeClient(pieces=["10월 30일까지 ", "내세요."]), "언제까지요?")
    assert conversation.turns[-1].unknown == ["10월 30일"]


def test_no_warning_text_when_ok():
    assert unknown_warning([]) == ""
