"""2단계: 원문 복원

사진 속 문서의 글자를 Claude의 이미지 인식으로 텍스트로 옮깁니다.
지시문은 prompts/transcribe.txt에 있습니다.
"""

from pathlib import Path

MODEL = "claude-sonnet-5"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "transcribe.txt"

NO_DOCUMENT = "문서를 찾을 수 없음"
TOO_BLURRY = "사진이 흐려서 읽을 수 없음"
UNREADABLE = "[판독불가]"

# [판독불가]가 이만큼 넘으면 사진이 너무 흐리다고 보고 멈춥니다.
MAX_UNREADABLE_COUNT = 15
MAX_UNREADABLE_RATIO = 0.2
# [판독불가]를 빼고 남은 글자가 이보다 적으면 읽을 내용이 없다고 봅니다.
MIN_READABLE_CHARS = 20


class TranscribeError(Exception):
    """원문 복원이 제대로 되지 않았을 때 쓰는 오류입니다. 메시지는 사용자에게 그대로 보여줍니다."""


def transcribe(client, media_type, image_data):
    """사진을 Claude에게 보내 문서 글자를 그대로 옮긴 텍스트를 받아옵니다."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=PROMPT_FILE.read_text(encoding="utf-8"),
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": media_type, "data": image_data},
                    },
                    {"type": "text", "text": "이 사진 속 문서의 글자를 규칙에 맞게 그대로 옮겨 주세요."},
                ],
            }
        ],
    )

    if response.stop_reason == "refusal":
        raise TranscribeError("AI가 이 사진의 글자 옮기기를 거절했습니다. 사진 내용을 확인해 주세요.")

    text = "".join(block.text for block in response.content if block.type == "text").strip()
    _check_quality(text)

    if response.stop_reason == "max_tokens":
        text += "\n\n(주의: 문서가 너무 길어 글자 옮기기가 중간에 잘렸습니다. 원문 확인 필요)"
    return text


def _check_quality(text):
    """문서가 아니거나 너무 흐린 사진이면 이유를 담아 멈춥니다."""
    readable = text.replace(UNREADABLE, "").replace(NO_DOCUMENT, "").replace(TOO_BLURRY, "").strip()

    if NO_DOCUMENT in text and len(readable) < MIN_READABLE_CHARS:
        raise TranscribeError(
            "사진에서 문서를 찾지 못했습니다.\n"
            "종이 문서가 사진 가운데에 크게 나오도록 다시 찍어 주세요."
        )

    unreadable_count = text.count(UNREADABLE)
    word_count = len(readable.split()) + unreadable_count
    too_many = unreadable_count >= MAX_UNREADABLE_COUNT
    too_high_ratio = word_count > 0 and unreadable_count / word_count > MAX_UNREADABLE_RATIO

    if TOO_BLURRY in text or len(readable) < MIN_READABLE_CHARS or too_many or too_high_ratio:
        detail = f" (읽지 못한 곳 {unreadable_count}군데)" if unreadable_count else ""
        raise TranscribeError(
            f"사진이 흐리거나 가려져서 읽을 수 없는 부분이 많습니다{detail}.\n"
            "밝은 곳에서, 흔들리지 않게, 문서 전체가 나오도록 다시 찍어 주세요."
        )
