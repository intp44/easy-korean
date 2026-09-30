"""쉬운말 도우미 - 웹 화면 (Streamlit)

실행:
    streamlit run app.py

화면은 pipeline.py가 제공하는 기능(원문 준비, 쉬운 한국어 스트림, 에러 설명)만 불러 씁니다.
올린 사진과 글은 메모리에서만 쓰고, 서버에는 어떤 파일도 저장하지 않습니다.

비밀 설정 (내 맥: .streamlit/secrets.toml / 배포: Streamlit Cloud의 Secrets 칸):
    APP_PASSWORD       입장 비밀번호. 없으면 아무도 들어올 수 없습니다.
    ANTHROPIC_API_KEY  Claude API 키. 없으면 .env에서 읽습니다.
"""

import hashlib
import hmac
import html
import os
import time
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv

from pipeline import (
    EasyKoreanStream,
    convert_step_message,
    explain_error,
    prepare_photo,
    prepare_text,
)
from verify import missing_report

BASE_DIR = Path(__file__).resolve().parent
SECTION_TITLES = ["[해야 할 일]", "[쉬운 설명]", "[어려운 말 풀이]"]

st.set_page_config(page_title="쉬운말 도우미", page_icon="📄", layout="centered")

st.markdown(
    """
    <style>
    /* 폰 화면 기준으로 좁게, 가운데 정렬 */
    .block-container { max-width: 640px; padding-top: 2rem; padding-bottom: 3rem; }
    h1 { text-align: center; font-size: 2.1rem !important; word-break: keep-all; }
    .intro { text-align: center; font-size: 1.1rem; color: #111; margin-bottom: 1.2rem; word-break: keep-all; }
    /* 탭 두 개를 폰 폭에 반씩 */
    div[data-baseweb="tab-list"] { gap: 0; }
    button[data-baseweb="tab"] { flex: 1; justify-content: center; }
    button[data-baseweb="tab"] p { font-size: 1rem; font-weight: 800; }
    /* 작은 안내 글도 진하게 */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
    .stCaption, .stCaption p { color: #333 !important; }
    /* 사진 올리기 칸의 영어 안내를 쉬운 한국어로 */
    [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [data-testid="stFileUploaderDropzone"] button { font-size: 0; }
    [data-testid="stFileUploaderDropzone"] button::after { content: "📷 사진 찍기·고르기"; font-size: 1.05rem; }
    /* 큰 버튼 */
    div.stButton > button, div.stDownloadButton > button {
        min-height: 3.2rem; font-size: 1.15rem; font-weight: 700;
    }
    /* [해야 할 일] 강조 상자 */
    .todo-box {
        background: #FFF3C4; border: 3px solid #8A5A00; border-radius: 14px;
        padding: 1rem 1.2rem; color: #111; line-height: 1.8; white-space: pre-wrap;
        margin: 0.6rem 0 1.2rem;
    }
    .todo-box .box-title { font-size: 1.25rem; font-weight: 800; margin-bottom: 0.3rem; }
    /* 원문 대조 검증: 빠진 정보 경고 상자 */
    .missing-box {
        background: #FDE7E9; border: 3px solid #A4001D; border-radius: 14px;
        padding: 1rem 1.2rem; color: #111; line-height: 1.7; margin: -0.4rem 0 1.2rem;
    }
    .missing-box .box-title { font-size: 1.15rem; font-weight: 800; color: #7A0016; margin-bottom: 0.4rem; }
    .missing-box ul { margin: 0; padding-left: 1.2rem; }
    .missing-box li { font-size: 1.1rem; font-weight: 700; }
    .check-ok { color: #1B5E20; font-size: 0.9rem; margin: -0.6rem 0 1rem; }
    .plain-text { color: #111; line-height: 1.9; white-space: pre-wrap; }
    .section-title { font-size: 1.2rem; font-weight: 800; margin: 0.8rem 0 0.3rem; }
    .original-text { color: #111; line-height: 1.7; white-space: pre-wrap; font-size: 0.95rem; }
    .chosen { text-align: center; color: #111; margin: 0.4rem 0; }
    .privacy-note { word-break: keep-all; text-align: center; color: #333; font-size: 0.85rem; margin-top: 2.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def read_secret(name):
    """Streamlit 비밀 설정에서 값을 읽습니다. 비밀 설정이 아예 없거나 값이 비어 있으면 None."""
    try:
        value = st.secrets.get(name)
    except Exception:  # 비밀 설정 파일이 하나도 없을 때
        return None
    value = str(value).strip() if value is not None else ""
    return value or None


def current_api_key():
    """API 키는 비밀 설정(ANTHROPIC_API_KEY)을 먼저 찾고, 없으면 .env에서 읽습니다. 둘 다 없으면 None."""
    api_key = read_secret("ANTHROPIC_API_KEY")
    if api_key:
        return api_key
    load_dotenv(BASE_DIR / ".env")
    return os.environ.get("ANTHROPIC_API_KEY") or None


@st.cache_resource(max_entries=1)
def _make_client(key_fingerprint, _api_key):
    """Claude 연결을 만듭니다. 같은 키(지문)면 만들어 둔 연결을 재사용하고, 키가 바뀌면 새로 만듭니다.
    key_fingerprint: 키를 알아볼 수 없게 바꾼 값(지문). 키 자체는 기억 목록의 이름표로 쓰지 않습니다.
    _api_key: 밑줄로 시작하는 값은 Streamlit이 이름표에 쓰지 않습니다."""
    return anthropic.Anthropic(api_key=_api_key)


def get_client():
    """지금 설정된 키로 Claude 연결을 돌려줍니다. 비밀 설정의 키를 고치면 재시작 없이 새 키를 씁니다."""
    api_key = current_api_key()
    if api_key is None:
        return None
    return _make_client(hashlib.sha256(api_key.encode("utf-8")).hexdigest(), api_key)


# ── 입장 비밀번호 ──────────────────────────────────────
MAX_WRONG_TRIES = 5
LOCK_SECONDS = 60


def password_gate():
    """비밀번호를 맞게 넣어야 변환 화면이 나옵니다. 맞으면 이 접속이 끝날 때까지 다시 묻지 않습니다.
    비밀번호 설정(APP_PASSWORD)이 없으면 아무도 들어오지 못하게 막습니다."""
    if st.session_state.get("signed_in"):
        return

    st.title("📄 쉬운말 도우미")
    expected = read_secret("APP_PASSWORD")
    if expected is None:
        st.error("🔧 관리자 설정이 필요해요. 아직 입장 비밀번호가 정해지지 않았어요.")
        st.stop()

    locked_for = st.session_state.get("locked_until", 0) - time.time()
    if locked_for > 0:
        st.error(f"⛔ 비밀번호를 {MAX_WRONG_TRIES}번 틀려서 잠시 막았어요. {int(locked_for) + 1}초 뒤에 다시 해 주세요.")
        st.button("🔄 다시 해 보기", use_container_width=True)
        st.stop()

    with st.form("password_form", clear_on_submit=True):
        typed = st.text_input("🔑 비밀번호를 입력해 주세요", type="password")
        submitted = st.form_submit_button("들어가기", type="primary", use_container_width=True)

    if submitted:
        # 글자를 하나씩 비교하는 데 걸리는 시간으로 비밀번호를 짐작하지 못하게, 안전한 비교 방식을 씁니다.
        if hmac.compare_digest(typed.encode("utf-8"), expected.encode("utf-8")):
            st.session_state.signed_in = True
            st.session_state.wrong_tries = 0
            st.rerun()
        st.session_state.wrong_tries = st.session_state.get("wrong_tries", 0) + 1
        if st.session_state.wrong_tries >= MAX_WRONG_TRIES:
            st.session_state.wrong_tries = 0
            st.session_state.locked_until = time.time() + LOCK_SECONDS
            st.rerun()
        st.error("비밀번호가 맞지 않아요")
    st.stop()


password_gate()


# ── 화면 상태 ──────────────────────────────────────────
# running: 바꾸는 중인지 / output: 마지막 결과나 에러 / source: 마지막으로 넣은 입력 종류
# input_round: 입력 칸 번호. 끝나면 번호를 바꿔서 올린 사진·글을 비웁니다.
for key, value in {"running": False, "output": None, "source": None, "input_round": 0, "notice": None}.items():
    st.session_state.setdefault(key, value)


def remember_source(kind):
    st.session_state.source = kind


def start():
    """'쉬운 말로 바꾸기'를 눌렀을 때. 이미 바꾸는 중이면 아무것도 하지 않습니다 (중복 요금 방지)."""
    if st.session_state.running:
        return
    st.session_state.running = True
    st.session_state.output = None
    st.session_state.notice = None


def pick_input(uploaded, pasted):
    """사진과 글 중 무엇을 바꿀지 고릅니다. 둘 다 있으면 마지막으로 넣은 것을 씁니다."""
    inputs = {"upload": uploaded, "text": (pasted or "").strip() or None}
    if st.session_state.source and inputs.get(st.session_state.source):
        return st.session_state.source, inputs[st.session_state.source]
    for kind, value in inputs.items():
        if value:
            return kind, value
    return None, None


def split_sections(text):
    """결과를 [해야 할 일], [쉬운 설명], [어려운 말 풀이] 구역으로 나눕니다. 제목을 못 찾으면 None."""
    positions = [(text.find(title), title) for title in SECTION_TITLES]
    if any(pos < 0 for pos, _ in positions):
        return None
    positions.sort()
    sections = {}
    for i, (pos, title) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(text)
        sections[title] = text[pos + len(title) : end].strip()
    return sections


def as_html(text):
    return html.escape(text)


def for_screen(pieces):
    """흘려 보여줄 조각을 화면용으로 바꿉니다. (*, _ 같은 글자가 굵은 글씨로 바뀌지 않게, 줄바꿈은 그대로)"""
    for piece in pieces:
        for mark in "\\`*_~#[]<>|":
            piece = piece.replace(mark, "\\" + mark)
        yield piece.replace("\n", "  \n")


STEP_LABELS = [
    (("사진 준비", "원문 복원", "이름·주소 찾는"), "🔎 1/3 글자 읽는 중"),
    (("개인정보 가리는",), "🙈 2/3 개인정보 가리는 중"),
    (("쉬운 한국어로 바꾸는",), "✏️ 3/3 쉬운 말로 바꾸는 중"),
]


def run(kind, value):
    """고른 입력을 쉬운 말로 바꿉니다. 결과나 에러는 화면 상태(output)에 담습니다. 파일은 만들지 않습니다."""
    client = get_client()
    if client is None:
        st.session_state.output = {"error": "API 키가 없어서 시작할 수 없어요. 관리자에게 알려 주세요."}
        return

    status = st.status("🔎 1/3 글자 읽는 중", expanded=True)
    stream_area = st.empty()

    def report(message):
        """pipeline.py의 진행 상황 문장을 그대로 보여주고, 제목은 쉬운 단계 이름으로 바꿉니다."""
        status.write(message.strip())
        for keywords, label in STEP_LABELS:
            if any(word in message for word in keywords):
                status.update(label=label)

    try:
        if kind == "text":
            masked_text = prepare_text(client, value, report)
        else:
            masked_text = prepare_photo(client, value.name, value.getvalue(), report)

        report(convert_step_message(kind != "text"))
        stream = EasyKoreanStream(client, masked_text)  # 파일 이름을 주지 않으므로 저장하지 않습니다.
        with stream_area.container():
            st.write_stream(for_screen(stream))

        status.update(label="✅ 다 바꿨어요", state="complete", expanded=False)
        # 검증은 결과가 끝까지 다 흘러나온 뒤 EasyKoreanStream 안에서 합니다.
        st.session_state.output = {"result": stream.result, "original": str(masked_text), "check": stream.check}
    except Exception as error:  # 어떤 에러든 쉬운 말 안내로 바꿉니다.
        stream_area.empty()  # 흘려 보여주던 반쪽짜리 글은 지웁니다.
        status.update(label="⚠️ 바꾸지 못했어요", state="error", expanded=False)
        st.session_state.output = {"error": explain_error(error)}


def show_check(check):
    """원문 대조 검증 결과를 보여줍니다. 빠진 게 있으면 빠진 값을 직접 보여줍니다."""
    if check is None or not check.checked:
        return
    if check.ok:
        st.markdown('<div class="check-ok">✅ 원문의 날짜·금액·번호가 모두 들어있어요</div>', unsafe_allow_html=True)
        return
    items = "".join(f"<li>{as_html(item.kind)}: {as_html(item.value)}</li>" for item in check.missing)
    st.markdown(
        '<div class="missing-box"><div class="box-title">⚠️ 원문에 있는 정보 중 결과에 빠진 게 있어요. 꼭 확인하세요</div>'
        f"<ul>{items}</ul></div>",
        unsafe_allow_html=True,
    )


def show_result(output):
    result = output["result"]
    check = output.get("check")
    st.success("✅ 쉬운 말로 바꿨어요")

    sections = split_sections(result)
    if sections is None:
        show_check(check)
        st.markdown(f'<div class="plain-text">{as_html(result)}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="todo-box"><div class="box-title">📌 해야 할 일</div>'
            f"{as_html(sections['[해야 할 일]'])}</div>",
            unsafe_allow_html=True,
        )
        show_check(check)
        st.markdown('<div class="section-title">💬 쉬운 설명</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="plain-text">{as_html(sections["[쉬운 설명]"])}</div>', unsafe_allow_html=True)
        with st.expander("📖 어려운 말 풀이"):
            st.markdown(f'<div class="plain-text">{as_html(sections["[어려운 말 풀이]"])}</div>', unsafe_allow_html=True)

    with st.expander("📄 원문 보기 (개인정보는 가렸어요)"):
        st.markdown(f'<div class="original-text">{as_html(output["original"])}</div>', unsafe_allow_html=True)

    report = missing_report(check)
    download_text = result + (f"\n\n{report}\n" if report else "\n")
    st.download_button(
        "⬇️ 결과 내려받기",
        data=download_text.encode("utf-8"),
        file_name="쉬운말_결과.txt",
        mime="text/plain",
        on_click="ignore",
        use_container_width=True,
    )


# ── 화면 ──────────────────────────────────────────────
st.title("📄 쉬운말 도우미")
st.markdown('<div class="intro">어려운 안내문을 사진으로 찍으면 쉬운 말로 바꿔드려요</div>', unsafe_allow_html=True)

running = st.session_state.running
round_no = st.session_state.input_round

tab_upload, tab_text = st.tabs(["📷 사진 찍기·고르기", "✍️ 글 붙여넣기"])
with tab_upload:
    uploaded = st.file_uploader(
        "버튼을 누르면 사진을 찍거나 앨범에서 고를 수 있어요. 안내문이 화면에 꽉 차게 찍어 주세요.",
        type=["jpg", "jpeg", "png", "heic"],
        key=f"upload_{round_no}",
        on_change=remember_source,
        args=("upload",),
        disabled=running,
    )
    st.caption("jpg, png, heic 사진 · 20MB까지")
with tab_text:
    pasted = st.text_area(
        "받은 안내문 글을 여기에 붙여 넣어 주세요",
        key=f"text_{round_no}",
        height=200,
        on_change=remember_source,
        args=("text",),
        disabled=running,
    )

kind, value = pick_input(uploaded, pasted)
if kind and not running:
    chosen = {"upload": f"📷 올린 사진: {uploaded.name if uploaded else ''}", "text": "✍️ 붙여 넣은 글"}
    st.markdown(f'<div class="chosen">바꿀 것 → {as_html(chosen[kind])}</div>', unsafe_allow_html=True)

st.button(
    "⏳ 바꾸는 중이에요…" if running else "✨ 쉬운 말로 바꾸기",
    type="primary",
    use_container_width=True,
    disabled=running,
    on_click=start,
)

if running:
    if kind is None:
        st.session_state.running = False
        st.session_state.notice = "먼저 사진을 찍거나 고르거나, 글을 붙여 넣어 주세요."
        st.rerun()
    run(kind, value)
    # 끝나면 입력 칸을 새로 만들어서, 올린 사진과 글을 메모리에서 비웁니다.
    st.session_state.running = False
    st.session_state.input_round += 1
    st.session_state.source = None
    st.rerun()

if st.session_state.notice:
    st.warning(f"👆 {st.session_state.notice}")

output = st.session_state.output
if output and "error" in output:
    st.error(f"⚠️ {output['error']}")
elif output:
    show_result(output)

st.markdown(
    '<div class="privacy-note">🔒 올린 사진과 글은 쉬운 말로 바꾸기 위해 AI 서비스로 보내지지만, 어디에도 저장하지 않아요. 결과를 보관하려면 내려받기를 눌러주세요.</div>',
    unsafe_allow_html=True,
)
