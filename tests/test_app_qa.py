"""화면의 묻고 답하기 (app.py) — Streamlit 화면 시험 도구(AppTest)와 가짜 AI로 시험합니다.

- 비밀 설정은 시험용 가짜 값만 넣습니다. (진짜 .streamlit/secrets.toml은 읽지 않습니다)
- Claude 연결은 가짜(FakeClient)로 바꿔 끼웁니다. 모든 값은 가짜입니다.
- 화면 시험 도구의 한계: 화면이 스스로 다시 그려진 뒤(st.rerun) 이번에 그리지 않은 버튼이 시험 도구 안에 남아,
  다음 실행 때 그 버튼이 눌린 것처럼 동작합니다. 실제 브라우저는 이런 버튼을 지웁니다.
  그래서 상호작용 한 번마다 settle()로 화면 상태만 옮겨 새로 열어, 브라우저처럼 남은 버튼을 없앱니다.
"""

from pathlib import Path

import anthropic
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from fakes import FakeClient, text_block
from qa import EXAMPLE_QUESTIONS, FAILED_ANSWER, MAX_QUESTIONS, NO_MORE_QUESTIONS, Conversation
from redact import redact
from simplify import MaskedText
from verify import check

APP = Path(__file__).resolve().parent.parent / "app.py"
MASKED = MaskedText(redact("과태료 고지서\n납부기한: 2026. 10. 20.\n금액: 96,000원\n담당자: 이가상 주무관 (051-000-1234)")[0])
RESULT = "[해야 할 일]\n- 언제까지: 2026. 10. 20.\n\n[쉬운 설명]\n과태료를 내세요.\n\n[어려운 말 풀이]\n- 과태료: 벌로 내는 돈"


@pytest.fixture
def fake(monkeypatch):
    client = FakeClient(pieces=["2026. 10. 20.까지 ", "내세요."])
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: client)
    st.cache_resource.clear()
    return client


# 화면 상태 중 옮길 것 (입력 칸 같은 위젯 값은 옮기지 않습니다)
KEPT_STATE = ("signed_in", "output", "running", "source", "input_round", "notice", "qa_pending")


def new_app(state):
    at = AppTest.from_file(str(APP), default_timeout=15)
    at.secrets["APP_PASSWORD"] = "시험용"
    at.secrets["ANTHROPIC_API_KEY"] = "시험용-가짜-키"
    for key, value in state.items():
        at.session_state[key] = value
    return at.run()


def open_app(with_result=True):
    state = {"signed_in": True}
    if with_result:
        state["output"] = {
            "result": RESULT, "original": str(MASKED), "check": check(MASKED, RESULT),
            "help": None, "qa": Conversation(MASKED, RESULT),
        }
    return new_app(state)


def settle(at):
    """브라우저처럼 남은 버튼을 없애고 화면을 다시 엽니다. 화면 상태(결과, 대화 기록)는 그대로 옮깁니다."""
    return new_app({key: at.session_state[key] for key in KEPT_STATE if key in at.session_state})


def screen_text(at):
    return " ".join(str(m.value) for m in at.markdown) + " ".join(str(e.value) for e in at.error)


def conversation(at):
    return at.session_state["output"]["qa"]


def ask_typed(at, question):
    at.chat_input(key="qa_input").set_value(question)
    return settle(at.run())


def test_qa_area_only_after_result(fake):
    assert "궁금한 걸 물어보세요" not in screen_text(open_app(with_result=False))
    at = open_app()
    assert "궁금한 걸 물어보세요" in screen_text(at)
    assert [b.label for b in at.button if b.key and b.key.startswith("qa_example")] == [f"🙋 {q}" for q in EXAMPLE_QUESTIONS]
    assert at.caption[-1].value == f"질문 {MAX_QUESTIONS}번 남았어요"


def test_example_button_asks_once(fake):
    at = open_app()
    at = settle(at.button(key="qa_example_0").click().run())
    assert len(fake.calls) == 1   # 중복 호출 없음
    assert EXAMPLE_QUESTIONS[0] in fake.calls[0]["messages"][-1]["content"]
    assert "2026. 10. 20.까지 내세요." in screen_text(at)
    assert at.caption[-1].value == "질문 4번 남았어요"
    assert not any(b.key and b.key.startswith("qa_example") for b in at.button)   # 예시 버튼은 처음에만


def test_typed_question_is_masked_on_screen_and_to_ai(fake):
    at = ask_typed(open_app(), "성명: 홍길동, 주민번호 900101-1234567, 010-9876-5432로 연락받을 수 있나요?")
    shown, sent = screen_text(at), str(fake.calls[0]["messages"])
    for private in ("홍길동", "1234567", "9876-5432"):
        assert private not in shown and private not in sent
    assert "성명: 홍○○, 주민번호 900101-1******, 010-****-****로" in shown


def test_blocked_after_five_questions(fake):
    at = open_app()
    for i in range(MAX_QUESTIONS):
        at = ask_typed(at, f"질문 {i}")
    assert len(fake.calls) == MAX_QUESTIONS
    assert at.chat_input(key="qa_input").disabled
    assert at.info[-1].value == f"💡 {NO_MORE_QUESTIONS}"
    at = ask_typed(at, "여섯 번째")
    assert len(fake.calls) == MAX_QUESTIONS


def test_error_keeps_result_and_previous_talk(fake):
    at = ask_typed(open_app(), "첫 질문")
    fake.stop_reason = None   # 다음 답은 도중에 끊김
    at = ask_typed(at, "둘째 질문")
    shown = screen_text(at)
    assert "2026. 10. 20.까지 내세요." in shown                 # 이전 답 그대로
    assert "과태료를 내세요." in shown                           # 위의 결과 그대로
    assert at.error[-1].value == f"⚠️ {FAILED_ANSWER}"           # 그 질문에만 안내
    assert len(at.error) == 1
    assert at.caption[-1].value == "질문 4번 남았어요"           # 실패한 질문은 횟수에서 빠짐
    assert not at.chat_input(key="qa_input").disabled


def test_unknown_value_warning_under_answer(fake):
    fake.pieces = ["보통 10월 30일까지 ", "내요."]
    at = ask_typed(open_app(), "언제까지 내요?")
    assert "⚠️ 이 답에 문서에 없는 값(10월 30일)이 있어요. 원문을 확인하세요" in screen_text(at)


def test_input_and_examples_blocked_while_answering(fake):
    # 답을 흘려 보여주는 도중에 화면이 멈춘 순간을 만들어, 그때 입력 칸과 예시 버튼이 막혀 있는지 봅니다.
    def stop_midway(**kwargs):
        fake.calls.append(kwargs)
        st.stop()

    fake.messages.stream = stop_midway
    at = open_app()
    at.button(key="qa_example_1").click().run()
    assert at.chat_input(key="qa_input").disabled
    assert all(at.button(key=f"qa_example_{i}").disabled for i in range(len(EXAMPLE_QUESTIONS)))
    assert at.session_state["qa_pending"] is None   # 다시 그려도 같은 질문을 또 보내지 않음


def test_new_document_clears_talk(fake):
    at = ask_typed(open_app(), "첫 질문")
    assert len(conversation(at).turns) == 1
    # 새 글을 넣고 바꾸기: 이름·주소 찾기(가짜 JSON) → 가리기 → 변환(가짜 스트림) → 도움 고르기(도구 없음)
    fake.blocks = [text_block('{"names": [], "addresses": []}')]
    fake.pieces = [RESULT]
    at.text_area(key=f"text_{at.session_state['input_round']}").set_value("새 안내문입니다. 2026. 10. 20.까지 내세요.").run()
    at.button[[b.label for b in at.button].index("✨ 쉬운 말로 바꾸기")].click().run()
    assert conversation(at).turns == []
    assert "첫 질문" not in screen_text(at)
    assert at.caption[-1].value == f"질문 {MAX_QUESTIONS}번 남았어요"
