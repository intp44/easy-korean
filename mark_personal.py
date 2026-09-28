"""txt 파일용 이름·주소 표시 단계

txt 파일에는 원문 복원 단계가 없어서, 개인 이름·주소 표시([[이름:…]], [[주소:…]])가 붙어 있지 않습니다.
이 단계에서 AI에게 개인 이름·주소 목록만 받아, 코드가 원문에 표시를 붙입니다.
AI가 글을 다시 쓰지 않으므로 원문 내용은 절대 바뀌지 않습니다.
지시문은 prompts/mark_personal.txt에 있습니다.
"""

import json
import re
from pathlib import Path

MODEL = "claude-sonnet-5"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "mark_personal.txt"

_SCHEMA = {
    "type": "object",
    "properties": {
        "names": {"type": "array", "items": {"type": "string"}},
        "addresses": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["names", "addresses"],
    "additionalProperties": False,
}


class MarkError(Exception):
    """이름·주소를 찾지 못했을 때 쓰는 오류입니다. 메시지는 사용자에게 그대로 보여줍니다."""


def mark_personal(client, text):
    """원문에서 개인 이름·주소를 찾아 표시를 붙인 글을 돌려줍니다. 이 글은 저장하지 않습니다."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        system=PROMPT_FILE.read_text(encoding="utf-8"),
        messages=[{"role": "user", "content": f"<원문>\n{text}\n</원문>"}],
        output_config={
            "effort": "medium",
            "format": {"type": "json_schema", "schema": _SCHEMA},
        },
    )

    if response.stop_reason in ("refusal", "max_tokens"):
        raise MarkError("AI가 이름·주소를 찾지 못했습니다. 개인정보가 새지 않도록 여기서 멈춥니다.")

    found = json.loads(next(block.text for block in response.content if block.type == "text"))
    text = _add_markers(text, "주소", found["addresses"])
    return _add_markers(text, "이름", found["names"])


def _add_markers(text, label, values):
    """원문에서 찾은 글자 앞뒤에 [[이름:…]] 같은 표시를 붙입니다. 긴 것부터 붙여서 겹치지 않게 합니다."""
    for value in sorted({v.strip() for v in values if v.strip()}, key=len, reverse=True):
        # 줄바꿈·띄어쓰기가 조금 달라도 찾을 수 있게 합니다. 이미 표시 안에 들어간 글자는 건너뜁니다.
        pattern = r"\s+".join(re.escape(part) for part in value.split())
        text = re.sub(
            r"(?<!\[\[이름:)(?<!\[\[주소:)" + pattern,
            lambda m: f"[[{label}:{' '.join(m.group(0).split())}]]",
            text,
        )
    return text
