"""쉬운말 도우미 - 웹 화면 (Streamlit)

실행:
    streamlit run app.py

화면은 pipeline.py가 제공하는 기능(원문 준비, 쉬운 한국어 스트림, 에러 설명)만 불러 씁니다.
올린 사진과 글은 메모리에서만 쓰고, 서버에는 어떤 파일도 저장하지 않습니다.
"""

import html
import os
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
    /* 탭 세 개가 폰 폭에 모두 보이게 */
    div[data-baseweb="tab-list"] { gap: 0; justify-content: space-between; }
    button[data-baseweb="tab"] { padding-left: 0.1rem; padding-right: 0.1rem; }
    button[data-baseweb="tab"] p { font-size: 0.8rem; font-weight: 800; }
    /* 작은 안내 글도 진하게 */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p,
    .stCaption, .stCaption p { color: #333 !important; }
    /* 사진 올리기 칸의 영어 안내를 쉬운 한국어로 */
    [data-testid="stFileUploaderDropzoneInstructions"] { display: none; }
    [data-testid="stFileUploaderDropzone"] button { font-size: 0; }
    [data-testid="stFileUploaderDropzone"] button::after { content: "📁 사진 고르기"; font-size: 1.05rem; }
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
    .plain-text { color: #111; line-height: 1.9; white-space: pre-wrap; }
    .section-title { font-size: 1.2rem; font-weight: 800; margin: 0.8rem 0 0.3rem; }
    .original-text { color: #111; line-height: 1.7; white-space: pre-wrap; font-size: 0.95rem; }
    .chosen { text-align: center; color: #111; margin: 0.4rem 0; }
    .privacy-note { word-break: keep-all; text-align: center; color: #333; font-size: 0.85rem; margin-top: 2.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_resource
def get_client():
    """Claude 연결을 한 번만 만들어 재사용합니다. API 키가 없으면 None을 돌려줍니다."""
    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    return anthropic.Anthropic()


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


def pick_input(uploaded, camera_photo, pasted):
    """세 입력 중 무엇을 바꿀지 고릅니다. 여러 개가 있으면 마지막으로 넣은 것을 씁니다."""
    inputs = {"upload": uploaded, "camera": camera_photo, "text": (pasted or "").strip() or None}
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
            name = value.name if kind == "upload" else "camera.jpg"
            masked_text = prepare_photo(client, name, value.getvalue(), report)

        report(convert_step_message(kind != "text"))
        stream = EasyKoreanStream(client, masked_text)  # 파일 이름을 주지 않으므로 저장하지 않습니다.
        with stream_area.container():
            st.write_stream(for_screen(stream))

        status.update(label="✅ 다 바꿨어요", state="complete", expanded=False)
        st.session_state.output = {"result": stream.result, "original": str(masked_text)}
    except Exception as error:  # 어떤 에러든 쉬운 말 안내로 바꿉니다.
        stream_area.empty()  # 흘려 보여주던 반쪽짜리 글은 지웁니다.
        status.update(label="⚠️ 바꾸지 못했어요", state="error", expanded=False)
        st.session_state.output = {"error": explain_error(error)}


def show_result(output):
    result = output["result"]
    st.success("✅ 쉬운 말로 바꿨어요")

    sections = split_sections(result)
    if sections is None:
        st.markdown(f'<div class="plain-text">{as_html(result)}</div>', unsafe_allow_html=True)
    else:
        st.markdown(
            f'<div class="todo-box"><div class="box-title">📌 해야 할 일</div>'
            f"{as_html(sections['[해야 할 일]'])}</div>",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="section-title">💬 쉬운 설명</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="plain-text">{as_html(sections["[쉬운 설명]"])}</div>', unsafe_allow_html=True)
        with st.expander("📖 어려운 말 풀이"):
            st.markdown(f'<div class="plain-text">{as_html(sections["[어려운 말 풀이]"])}</div>', unsafe_allow_html=True)

    with st.expander("📄 원문 보기 (개인정보는 가렸어요)"):
        st.markdown(f'<div class="original-text">{as_html(output["original"])}</div>', unsafe_allow_html=True)

    st.download_button(
        "⬇️ 결과 내려받기",
        data=result.encode("utf-8"),
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

tab_upload, tab_camera, tab_text = st.tabs(["🖼️ 사진 올리기", "📷 카메라로 찍기", "✍️ 글 붙여넣기"])
with tab_upload:
    uploaded = st.file_uploader(
        "안내문 사진을 골라 주세요",
        type=["jpg", "jpeg", "png", "heic"],
        key=f"upload_{round_no}",
        on_change=remember_source,
        args=("upload",),
        disabled=running,
    )
    st.caption("jpg, png, heic 사진 · 20MB까지")
with tab_camera:
    camera_photo = None
    if st.toggle("📷 카메라 켜기", key=f"camera_on_{round_no}", disabled=running):
        camera_photo = st.camera_input(
            "안내문이 화면에 꽉 차게 찍어 주세요",
            key=f"camera_{round_no}",
            on_change=remember_source,
            args=("camera",),
            disabled=running,
        )
    st.caption("카메라가 안 켜지면 '사진 올리기'를 누르고 '사진 찍기'를 골라도 돼요.")
with tab_text:
    pasted = st.text_area(
        "받은 안내문 글을 여기에 붙여 넣어 주세요",
        key=f"text_{round_no}",
        height=200,
        on_change=remember_source,
        args=("text",),
        disabled=running,
    )

kind, value = pick_input(uploaded, camera_photo, pasted)
if kind and not running:
    chosen = {"upload": f"🖼️ 올린 사진: {uploaded.name if uploaded else ''}", "camera": "📷 찍은 사진", "text": "✍️ 붙여 넣은 글"}
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
        st.session_state.notice = "먼저 사진을 올리거나, 찍거나, 글을 붙여 넣어 주세요."
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
    '<div class="privacy-note">🔒 올린 사진과 글은 저장하지 않아요. 결과를 보관하려면 내려받기를 눌러주세요.</div>',
    unsafe_allow_html=True,
)
