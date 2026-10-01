"""스트리밍 변환 (simplify.py, pipeline.py)

변환 도중 오류가 나면 반쪽 결과를 저장하지 않아야 합니다.
결과 파일은 samples/results 대신 테스트용 임시 폴더에 저장되게 바꿔서 시험합니다.
"""

import httpx
import pytest

import pipeline
from fakes import FakeClient
from simplify import TRUNCATED_NOTE, ConvertError, MaskedText

ORIGINAL = MaskedText("2026. 10. 20.까지 96,000원을 납부하세요.")


@pytest.fixture
def results_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "RESULTS_DIR", tmp_path)
    return tmp_path


def run_stream(client, input_file):
    stream = pipeline.EasyKoreanStream(client, ORIGINAL, input_file)
    shown = []
    for piece in stream:
        shown.append(piece)
    return stream, shown


def test_success_saves_result_and_checks(results_dir, tmp_path):
    client = FakeClient(pieces=["2026. 10. 20.까지 ", "96,000원을 내세요."])
    stream, shown = run_stream(client, tmp_path / "notice.txt")
    assert stream.result == "2026. 10. 20.까지 96,000원을 내세요."
    assert stream.saved_to.read_text(encoding="utf-8") == stream.result + "\n"
    assert stream.check.all_ok


@pytest.mark.parametrize("error", [
    httpx.ReadError("끊김"),
    RuntimeError("알 수 없는 오류"),
])
def test_error_midway_saves_nothing(results_dir, tmp_path, error):
    client = FakeClient(pieces=["2026. 10. 20.까지 ", "96,000원을", " 내세요."], fail_after=2, error=error)
    stream = pipeline.EasyKoreanStream(client, ORIGINAL, tmp_path / "notice.txt")
    with pytest.raises((ConvertError, RuntimeError)):
        for _ in stream:
            pass
    assert list(results_dir.glob("*_result.txt")) == []
    assert stream.result is None and stream.saved_to is None


def test_connection_lost_without_stop_reason_saves_nothing(results_dir, tmp_path):
    client = FakeClient(pieces=["반쪽 결과"], stop_reason=None)
    with pytest.raises(ConvertError, match="연결이 끊겼습니다"):
        run_stream(client, tmp_path / "notice.txt")
    assert list(results_dir.glob("*_result.txt")) == []


def test_refusal_saves_nothing(results_dir, tmp_path):
    client = FakeClient(pieces=["반쪽"], stop_reason="refusal")
    with pytest.raises(ConvertError, match="거절"):
        run_stream(client, tmp_path / "notice.txt")
    assert list(results_dir.glob("*_result.txt")) == []


def test_too_long_result_gets_warning_note(results_dir, tmp_path):
    client = FakeClient(pieces=["긴 결과"], stop_reason="max_tokens")
    stream, shown = run_stream(client, tmp_path / "notice.txt")
    assert shown[-1] == TRUNCATED_NOTE and stream.result.endswith(TRUNCATED_NOTE)


def test_screen_mode_saves_nothing(results_dir):
    client = FakeClient(pieces=["결과"])
    stream, _ = run_stream(client, None)
    assert stream.saved_to is None and list(results_dir.iterdir()) == []


def test_unmasked_text_is_refused():
    with pytest.raises(TypeError):
        list(pipeline.stream_easy_korean(FakeClient(pieces=["x"]), "가리지 않은 글"))


def test_explain_error_is_plain_korean():
    assert pipeline.explain_error(ConvertError("끊겼어요")) == "끊겼어요"
    assert pipeline.explain_error(ValueError("x")).startswith("알 수 없는 오류")
