"""도움 고르기 (에이전트 단계)

쉬운 한국어 변환과 검증이 끝난 뒤, AI(claude-haiku-4-5)가 문서를 보고
이 사용자에게 필요한 도움(도구)을 스스로 고릅니다. 문서 한 건당 AI 호출은 1번입니다.

도구 3개 (설명과 지시문은 prompts/agent.txt):
- make_schedule: 기한을 폰 캘린더에 넣는 일정 파일(.ics)
- draft_inquiry: 기관에 보낼 문의 문장 + 107 손말이음센터 안내
- make_checklist: 준비물 체크리스트

AI가 넘긴 값은 코드가 한 번 더 확인합니다.
- 일정 날짜가 가린 원문에 없으면 일정을 만들지 않습니다. (verify.py 규칙)
- 문의 문장의 전화번호가 원문에 없으면 그 번호를 뺍니다.
- 준비물이 원문과 전혀 겹치지 않으면 뺍니다.
AI에게는 개인정보를 가린 원문과 쉬운 한국어 결과만 보냅니다.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path

from verify import date_in_original, number_digits

MODEL = "claude-haiku-4-5"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "agent.txt"

# 107 안내는 AI가 쓰지 않고 이 글을 그대로 보여줍니다.
RELAY_107_GUIDE = """📞 전화가 어려우면 107 손말이음센터를 이용하세요. 수어 통역사나 중계사가 대신 전화해줘요.
 · 국번 없이 107로 문자 또는 영상통화
 · 인터넷: 107.kr (회원가입 후 이용)
 · 카카오톡: '손말이음센터' 채널 추가
 · 365일 24시간 이용 가능"""

_SCHEMAS = {
    "make_schedule": {
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "기한 날짜, YYYY-MM-DD"},
            "title": {"type": "string", "description": "짧은 일정 제목"},
        },
        "required": ["date", "title"],
        "additionalProperties": False,
    },
    "draft_inquiry": {
        "type": "object",
        "properties": {"message": {"type": "string", "description": "기관에 보낼 문의 문장. 이름 자리는 [이름]"}},
        "required": ["message"],
        "additionalProperties": False,
    },
    "make_checklist": {
        "type": "object",
        "properties": {"items": {"type": "array", "items": {"type": "string"}, "description": "원문에 나온 준비물"}},
        "required": ["items"],
        "additionalProperties": False,
    },
}

# 문의 문장 속 전화번호 모양: 055-000-1111, (055) 000-1111, 1588-0000, 01012345678
PHONE_IN_TEXT = re.compile(
    r"(?<![\d\-])(?:\(\s*0\d{1,2}\s*\)\s*\d{3,4}-\d{4}|0\d{1,2}[\s\-]\d{3,4}-\d{4}|1\d{3}-\d{4}|01\d\d{7,8})(?![\d\-])"
)


class HelpError(Exception):
    """도움 고르기가 실패했을 때 쓰는 오류입니다."""


@dataclass
class Schedule:
    day: date
    title: str
    ics: str   # 폰 캘린더에 넣을 일정 파일 내용

    @property
    def label(self):
        return f"{self.day.month}월 {self.day.day}일"


@dataclass
class HelpPlan:
    schedule: Schedule = None
    inquiry: str = None
    checklist: list = field(default_factory=list)
    dropped: list = field(default_factory=list)   # 원문과 안 맞아서 코드가 버린 것 (확인용)

    @property
    def empty(self):
        return self.schedule is None and not self.inquiry and not self.checklist


# ── 지시문 읽기 ───────────────────────────────────────
def _load_prompt():
    """prompts/agent.txt를 '## 지시문'과 '## 도구: 이름' 부분으로 나눕니다."""
    sections, name, lines = {}, None, []
    for line in PROMPT_FILE.read_text(encoding="utf-8").splitlines():
        header = re.match(r"^## (?:도구: )?(.+)$", line)
        if header:
            if name:
                sections[name] = "\n".join(lines).strip()
            name, lines = header.group(1).strip(), []
        else:
            lines.append(line)
    if name:
        sections[name] = "\n".join(lines).strip()
    return sections


def _tools(sections):
    return [
        {"name": name, "description": sections[name], "strict": True, "input_schema": schema}
        for name, schema in _SCHEMAS.items()
    ]


# ── AI가 넘긴 값 확인하기 ─────────────────────────────
def _check_schedule(value, masked_original, plan, today):
    try:
        picked = datetime.strptime(value.get("date", "").strip(), "%Y-%m-%d").date()
    except ValueError:
        plan.dropped.append(f"일정: 날짜 모양이 이상함 ({value.get('date')!r})")
        return
    found, original_year = date_in_original(masked_original, picked.year, picked.month, picked.day)
    if not found:
        plan.dropped.append(f"일정: 원문에 없는 날짜 ({picked.isoformat()})")
        return
    if original_year is None:
        # 원문에 연도가 없으면 AI가 추측한 연도 대신, 오늘 이후 가장 가까운 그 월·일로 정합니다.
        year = today.year if (picked.month, picked.day) >= (today.month, today.day) else today.year + 1
        picked = picked.replace(year=year)
    title = (value.get("title") or "문서 기한").strip()[:40]
    plan.schedule = Schedule(picked, title, make_ics(picked, title))


def _check_inquiry(value, masked_original, plan):
    message = (value.get("message") or "").strip()
    if not message:
        return
    allowed = number_digits(masked_original)
    for number in PHONE_IN_TEXT.findall(message):
        if re.sub(r"\D", "", number) not in allowed:
            plan.dropped.append(f"문의 문장: 원문에 없는 전화번호를 뺌 ({number})")
            message = _remove_number(message, number)
    # 번호를 뺀 자리에 남은 빈 괄호와 겹친 띄어쓰기를 정리합니다.
    message = re.sub(r"\(\s*\)", "", message)
    message = re.sub(r"[ \t]{2,}", " ", message).replace(" .", ".").replace(" ,", ",").strip()
    plan.inquiry = message


_JOIN = r"(?:/|,|또는|혹은)"


def _remove_number(message, number):
    """번호를 빼면서, 그 번호를 잇던 말("/", ",", "또는")도 한쪽만 함께 뺍니다.
    예: '051-000-1234 / 010-9999-8888' → '051-000-1234', '(051) 999-8888 또는 051-000-1234' → '051-000-1234'
        '문의: 02-111-2222로 연락' → '문의: [연락처]로 연락'
    """
    escaped = re.escape(number)
    for pattern in (rf"\s*{_JOIN}\s*{escaped}", rf"{escaped}\s*{_JOIN}\s*"):
        if re.search(pattern, message):
            return re.sub(pattern, "", message, count=1)
    # 이어진 다른 번호가 없으면, 사용자가 원문을 보고 채우도록 [연락처] 자리로 남깁니다.
    return message.replace(number, "[연락처]")


def _hangul_pairs(text):
    words = re.findall(r"[가-힣]{2,}", text)
    return {word[i:i + 2] for word in words for i in range(len(word) - 1)}


def _check_checklist(value, masked_original, plan):
    original_pairs = _hangul_pairs(masked_original)
    items = []
    for item in value.get("items") or []:
        item = str(item).strip()
        if not item or item in items:
            continue
        if _hangul_pairs(item) & original_pairs:
            items.append(item)
        else:
            plan.dropped.append(f"준비물: 원문에 없는 것 같아 뺌 ({item})")
    plan.checklist = items


# ── AI에게 묻기 (1번) ────────────────────────────────
def choose_help(client, masked_text, result, today=None):
    """AI가 문서에 맞는 도움을 골라 HelpPlan으로 돌려줍니다. 고른 게 없으면 비어 있는 HelpPlan."""
    sections = _load_prompt()
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=sections["지시문"],
        tools=_tools(sections),
        tool_choice={"type": "auto"},  # 맞는 도구가 없으면 아무것도 고르지 않아도 됩니다.
        messages=[{
            "role": "user",
            "content": f"<원문>\n{masked_text}\n</원문>\n\n<쉬운결과>\n{result}\n</쉬운결과>",
        }],
    )
    if response.stop_reason in ("refusal", "max_tokens"):
        raise HelpError(f"도움 고르기가 끝나지 않았습니다 ({response.stop_reason}).")

    plan, today = HelpPlan(), today or date.today()
    for block in response.content:
        if block.type != "tool_use" or not isinstance(block.input, dict):
            continue
        if block.name == "make_schedule" and plan.schedule is None:
            _check_schedule(block.input, masked_text, plan, today)
        elif block.name == "draft_inquiry" and plan.inquiry is None:
            _check_inquiry(block.input, masked_text, plan)
        elif block.name == "make_checklist" and not plan.checklist:
            _check_checklist(block.input, masked_text, plan)
    return plan


# ── 폰 캘린더 일정 파일 (.ics) ────────────────────────
def _ics_text(text):
    """일정 파일 안에서 특별한 뜻이 있는 글자(\\ ; , 줄바꿈)를 바꿔 씁니다."""
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line):
    """일정 파일 규칙: 한 줄은 75바이트를 넘지 않게, 넘으면 다음 줄을 띄어쓰기로 시작해 잇습니다."""
    out, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not out else 74):
            out.append(current.decode("utf-8"))
            current = b""
        current += encoded
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def make_ics(day, title, now=None):
    """하루 종일 일정 파일을 만듭니다. 알림: 전날 오전 9시, 3일 전 오전 9시."""
    now = now or datetime.now(timezone.utc)
    next_day = date.fromordinal(day.toordinal() + 1)
    summary = _ics_text(title)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//easy-korean//쉬운말 도우미//KO",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@easy-korean",
        f"DTSTAMP:{now.strftime('%Y%m%dT%H%M%SZ')}",
        f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{next_day.strftime('%Y%m%d')}",
        f"SUMMARY:{summary}",
        "DESCRIPTION:" + _ics_text("쉬운말 도우미에서 만든 일정입니다. 날짜는 원문에서 한 번 더 확인하세요."),
        "TRANSP:TRANSPARENT",
    ]
    # 하루 종일 일정은 그날 0시에 시작하므로, 전날 오전 9시 = 15시간 전 / 3일 전 오전 9시 = 2일 15시간 전
    for trigger, when in (("-PT15H", "내일"), ("-P2DT15H", "3일 뒤")):
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"TRIGGER:{trigger}",
            "DESCRIPTION:" + _ics_text(f"{when}: {title}"),
            "END:VALARM",
        ]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
