"""원문 대조 검증

개인정보를 가린 원문에서 "중요 정보"(날짜, 금액, 전화번호, 계좌번호, 이름표가 붙은 번호)를 뽑아,
쉬운 한국어 결과에 모두 들어 있는지 확인합니다. AI를 쓰지 않고 정해진 규칙으로만 확인하므로 결과가 항상 같습니다.

- 가려진 정보(* 나 ○가 들어간 것)는 검사하지 않습니다.
- 문서번호, 법 조항 번호(제22조 등), 쪽 번호는 검사하지 않습니다.
- 모양이 달라도 같은 값이면 같은 것으로 봅니다.
  (120,000원 = 12만 원 = 120000원 / 2026년 10월 16일 = 10월 16일 = 2026. 10. 16.)
"""

import re
from dataclasses import dataclass, field

# ── 검사하지 않을 부분 ─────────────────────────────────
# 이름표 뒤 줄 끝까지를 통째로 뺍니다.
SKIP_LABELED = re.compile(r"(?:문서\s?번호|시행\s?번호|공문\s?번호)[^\n]*")
# 법 조항: 제32조, 제160조 제3항, 제18조의2
LAW_ARTICLE = re.compile(r"제\s?\d+\s?(?:조|항|호|장|절|관)(?:\s?의\s?\d+)?")
# 쪽 번호: "- 1 -", "1/3쪽", "(1/2)", "3쪽", "페이지 2"
PAGE_NUMBER = re.compile(
    r"^[ \t]*[-–(]?\s*\d+\s*(?:/\s*\d+)?\s*[-–)]?[ \t]*$"
    r"|\d+\s*/\s*\d+\s*(?:쪽|페이지|page)"
    r"|(?<![\d])\d+\s*(?:쪽|페이지)"
    r"|(?:페이지|page|p\.)\s*\d+(?:\s*/\s*\d+)?",
    re.M | re.I,
)

# ── 중요 정보 모양 ─────────────────────────────────────
# 이름표가 붙은 번호 (납부·문의에 필요)
NUMBER_LABELS = r"전자\s?납부\s?번호|납부자\s?번호|납부\s?번호|고지\s?번호|고객\s?번호|접수\s?번호|신청\s?번호|관리\s?번호|계약\s?번호"
LABELED_NUMBER = re.compile(rf"({NUMBER_LABELS})\s*[:：|]?\s*(\d[\d\-]*\d)(?![\d*])")

_D = r"(?<![\d.\-])"
DATE_FULL = re.compile(_D + r"((?:19|20)\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
DATE_DOTTED = re.compile(_D + r"((?:19|20)\d{2})\s*[.\-/]\s*(\d{1,2})\s*[.\-/]\s*(\d{1,2})(?![\d\-])\.?")
DATE_MONTH_DAY = re.compile(_D + r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
DATE_SLASH = re.compile(r"(?<![\d./\-])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")

_NUM = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
# 12만 3,400원 / 120,000원 / 1억 2,000만 원 (숫자가 하나도 없는 것은 나중에 버립니다)
AMOUNT = re.compile(rf"(?<![\d,.])((?:(?:{_NUM})\s*(?:억|만|천)\s*)*(?:{_NUM})?)\s*원")
_UNITS = {"억": 100_000_000, "만": 10_000, "천": 1_000, None: 1, "": 1}

PHONE = re.compile(r"(?<![\d*\-])(0\d{1,2}-\d{3,4}-\d{4}|1\d{3}-\d{4})(?![\d*\-])")
ACCOUNT = re.compile(r"(?<![\d*\-])(\d{2,6}(?:-\d{1,8}){2,4})(?![\d*\-])")
ACCOUNT_AFTER_WORD = re.compile(r"계좌[^\d\n*]{0,15}(?<![\d*])(\d{10,14})(?![\d*])")

# 결과 쪽에서 번호를 찾을 때: 숫자와 - 로 이루어진 덩어리
NUMBER_RUN = re.compile(r"\d[\d\-]*\d|\d")


@dataclass
class Item:
    kind: str    # 종류 (날짜, 금액, 전화번호, 계좌번호, 고지번호 …)
    value: str   # 원문에 적힌 그대로의 값
    key: tuple   # 모양을 맞춘 비교용 값


@dataclass
class CheckResult:
    checked: list = field(default_factory=list)   # 검사한 중요 정보
    missing: list = field(default_factory=list)   # 결과에 빠진 중요 정보

    @property
    def ok(self):
        return not self.missing


def _blank(text, pattern):
    """검사하지 않을 부분을 같은 길이의 빈칸으로 바꿉니다. (위치가 틀어지지 않게)"""
    return pattern.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _digits(text):
    return re.sub(r"\D", "", text)


def _amount_value(text):
    """'12만 3,400' → 123400"""
    total = 0
    for number, unit in re.findall(rf"({_NUM})\s*(억|만|천)?", text):
        total += round(float(number.replace(",", "")) * _UNITS[unit])
    return total


def _valid_date(month, day):
    return 1 <= month <= 12 and 1 <= day <= 31


def extract(text):
    """글에서 중요 정보를 원문 순서대로 뽑습니다. 같은 값은 한 번만 넣습니다."""
    work = text
    for pattern in (SKIP_LABELED, LAW_ARTICLE, PAGE_NUMBER):
        work = _blank(work, pattern)

    found = []  # (위치, Item)

    def take(pattern, make):
        nonlocal work
        for m in pattern.finditer(work):
            item = make(m)
            if item is not None:
                found.append((m.start(), item))
        work = _blank(work, pattern)

    # 1) 이름표가 붙은 번호를 먼저 (전화·계좌 모양이어도 이 종류로 봅니다)
    take(LABELED_NUMBER, lambda m: Item(re.sub(r"\s", "", m.group(1)), m.group(2), ("번호", _digits(m.group(2)))))

    # 2) 날짜
    def full_date(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return Item("날짜", m.group(0).strip(), ("날짜", y, mo, d)) if _valid_date(mo, d) else None

    take(DATE_FULL, full_date)
    take(DATE_DOTTED, full_date)
    take(DATE_MONTH_DAY, lambda m: Item("날짜", m.group(0), ("날짜", None, int(m.group(1)), int(m.group(2))))
         if _valid_date(int(m.group(1)), int(m.group(2))) else None)
    take(DATE_SLASH, lambda m: Item("날짜", m.group(0), ("날짜", None, int(m.group(1)), int(m.group(2))))
         if _valid_date(int(m.group(1)), int(m.group(2))) else None)

    # 3) 금액
    def amount(m):
        number = m.group(1) or ""
        if not re.search(r"\d", number):
            return None
        return Item("금액", m.group(0).strip(), ("금액", _amount_value(number)))

    take(AMOUNT, amount)

    # 4) 전화번호 → 5) 계좌번호
    take(PHONE, lambda m: Item("전화번호", m.group(1), ("번호", _digits(m.group(1)))))

    def account(m):
        digits = _digits(m.group(1))
        if not 10 <= len(digits) <= 14:
            return None
        return Item("계좌번호", m.group(1), ("번호", digits))

    take(ACCOUNT, account)
    take(ACCOUNT_AFTER_WORD, lambda m: Item("계좌번호", m.group(1), ("번호", m.group(1))))

    items, seen = [], set()
    for _, item in sorted(found, key=lambda pair: pair[0]):
        if item.key not in seen:
            seen.add(item.key)
            items.append(item)
    return items


def _present(item, result_keys, result_numbers):
    kind = item.key[0]
    if kind == "날짜":
        _, year, month, day = item.key
        return any(
            k[0] == "날짜" and k[2] == month and k[3] == day and (year is None or k[1] in (None, year))
            for k in result_keys
        )
    if kind == "금액":
        return item.key in result_keys
    return item.key[1] in result_numbers


def check(masked_original, result):
    """가린 원문의 중요 정보가 결과에 모두 있는지 확인합니다."""
    checked = extract(masked_original)
    result_keys = {item.key for item in extract(result)}
    result_numbers = {_digits(run) for run in NUMBER_RUN.findall(result)}
    missing = [item for item in checked if not _present(item, result_keys, result_numbers)]
    return CheckResult(checked=checked, missing=missing)


def missing_report(check_result):
    """빠진 정보를 사람이 읽을 목록 글로 만듭니다. 빠진 게 없으면 빈 글."""
    if not check_result or check_result.ok:
        return ""
    lines = ["[확인 필요] 원문에 있는데 결과에 빠진 정보"]
    lines += [f"- {item.kind}: {item.value}" for item in check_result.missing]
    return "\n".join(lines)
