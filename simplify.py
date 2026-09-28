"""마지막 단계: 쉬운 한국어 변환

개인정보를 가린 원문을 prompts/rules.txt 규칙에 따라 쉬운 한국어로 바꿉니다.
두 가지 방식으로 쓸 수 있습니다.
- stream_easy_korean: 글 조각이 생길 때마다 하나씩 내보냅니다. (화면에 흘려 보여줄 때)
- make_easy_korean: 끝까지 다 만든 결과를 한 번에 돌려줍니다.
"""

from pathlib import Path

import anthropic
import httpx

MODEL = "claude-sonnet-5"
RULES_FILE = Path(__file__).resolve().parent / "prompts" / "rules.txt"
TRUNCATED_NOTE = "\n\n(주의: 결과가 너무 길어 중간에 잘렸습니다. 원문 확인 필요)"


class MaskedText(str):
    """개인정보 가리기를 마친 원문입니다.
    변환 단계는 이 표시가 붙은 글만 받아서, 가리기 전 글이 실수로 변환·화면에 나가지 않게 막습니다."""


class ConvertError(Exception):
    """쉬운 한국어 변환이 제대로 끝나지 않았을 때 쓰는 오류입니다. 메시지는 사용자에게 그대로 보여줍니다."""


def stream_easy_korean(client, masked_text):
    """쉬운 한국어 결과를 조각이 생길 때마다 하나씩 내보냅니다.
    중간에 오류가 나면 ConvertError 또는 anthropic 오류가 납니다. 그때까지 받은 조각은 버려야 합니다."""
    if not isinstance(masked_text, MaskedText):
        raise TypeError("개인정보를 가린 원문(MaskedText)만 쉬운 한국어로 바꿀 수 있습니다.")

    try:
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=RULES_FILE.read_text(encoding="utf-8"),
            messages=[
                {
                    "role": "user",
                    "content": f"다음 문서를 규칙에 맞게 쉬운 한국어로 바꿔 주세요.\n\n<원문>\n{masked_text}\n</원문>",
                }
            ],
        ) as stream:
            for piece in stream.text_stream:
                yield piece
            final = stream.get_final_message()
    except httpx.HTTPError:
        # 결과를 받는 도중 연결이 끊기면 SDK 오류가 아니라 이 오류가 날 수 있습니다.
        raise ConvertError("쉬운 한국어로 바꾸는 도중 인터넷 연결이 끊겼습니다. 연결을 확인하고 다시 실행하세요.")

    if final.stop_reason == "refusal":
        raise ConvertError("AI가 이 문서의 변환을 거절했습니다. 문서 내용을 확인해 주세요.")
    if final.stop_reason == "max_tokens":
        yield TRUNCATED_NOTE


def make_easy_korean(client, masked_text):
    """쉬운 한국어 결과를 끝까지 다 만든 뒤 한 번에 돌려줍니다."""
    return "".join(stream_easy_korean(client, masked_text))
