"""원문 대조 검증

AI를 쓰지 않고 정해진 규칙으로만 확인하므로 결과가 항상 같습니다. 두 방향으로 확인합니다.
1) 빠진 정보: 가린 원문의 "중요 정보"(날짜, 금액, 전화번호, 계좌번호, 이름표가 붙은 번호)가 결과에 모두 있는지
2) 원문에 그대로 적혀 있지 않은 값 (역방향): 결과의 중요 정보가 가린 원문에 실제로 있는지 → AI가 계산하거나 새로 쓴 값을 잡습니다.
   - 원문의 여러 금액을 더하거나 빼서 만든 새 금액, "14일 이내" 같은 기간을 바꾼 특정 날짜도 원문에 없는 값으로 봅니다.
   - 원문에 연도가 없는데 결과에 연도가 붙은 날짜는 월·일이 같으면 통과로 보고, 따로 기록합니다.

- 가려진 정보(* 나 ○가 들어간 것)는 검사하지 않습니다.
- 문서번호, 법 조항 번호(제22조 등), 쪽 번호는 검사하지 않습니다.
- 모양이 달라도 같은 값이면 같은 것으로 봅니다.
  (120,000원 = 12만 원 = 120000원 / 2026년 10월 16일 = 10월 16일 = 2026. 10. 16. = 26.10.16
   / (055) 000-1111 = 055-000-1111)
- 표에서 "원" 없이 적힌 금액도 알아봅니다.
  - "납부금액 96,000", "합계 | 120,000"처럼 금액 이름표(금액, 요금, 보험료, 과태료, 합계 등) 바로 뒤의 숫자
  - "금액(원)"이나 "금액" 머리글 칸, "(단위: 원)" 아래 표의 숫자
  - 단, 뒤에 ㎥·명·개·%·쪽 같은 단위가 붙은 숫자와 수량·인원·사용량 칸의 숫자는 금액으로 보지 않습니다.
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
# 두 자리 연도 점 날짜: 26.10.16 / 26. 10. 16. → 2026년 10월 16일
DATE_SHORT_YEAR = re.compile(_D + r"(\d{2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{1,2})(?![\d.\-]\d)\.?")
DATE_SLASH = re.compile(r"(?<![\d./\-])(\d{1,2})\s*/\s*(\d{1,2})(?![\d/])")

_NUM = r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?"
# 12만 3,400원 / 120,000원 / 1억 2,000만 원 (숫자가 하나도 없는 것은 나중에 버립니다)
AMOUNT = re.compile(rf"(?<![\d,.])((?:(?:{_NUM})\s*(?:억|만|천)\s*)*(?:{_NUM})?)\s*원")
_UNITS = {"억": 100_000_000, "만": 10_000, "천": 1_000, None: 1, "": 1}

PHONE = re.compile(r"(?<![\d*\-])(\(\s*0\d{1,2}\s*\)\s*\d{3,4}-\d{4}|0\d{1,2}-\d{3,4}-\d{4}|1\d{3}-\d{4})(?![\d*\-])")
ACCOUNT = re.compile(r"(?<![\d*\-])(\d{2,6}(?:-\d{1,8}){2,4})(?![\d*\-])")
ACCOUNT_AFTER_WORD = re.compile(r"계좌[^\d\n*]{0,15}(?<![\d*])(\d{10,14})(?![\d*])")

# ── 표 금액 ("원" 없이 적힌 금액) ──────────────────────
# 금액 이름표: 납부금액, 청구금액, 기본요금, 건강보험료, 과태료, 세액, 본인부담금, 수수료, 합계, 총액 …
AMOUNT_LABEL = r"[가-힣]*(?:금액|요금|보험료|과태료|세액|부담금|환급금|수수료|가산금|납부액|청구액)|합계|총계|소계|총액"
# 숫자 뒤에 이런 단위가 붙으면 금액이 아닙니다.
NOT_MONEY_UNIT = r"[ \t]*(?:[%㎥㎡명개건회일월년쪽세호층동권매장시분]|kWh|kg|원)"
LABELED_AMOUNT = re.compile(
    rf"(?<![가-힣])({AMOUNT_LABEL})(?:\s*\(\s*원\s*\))?(?:\s*[:：|])*\s*({_NUM})(?![\d,.])(?!{NOT_MONEY_UNIT})"
)
# 표 머리글: 이 말이 있으면 금액 칸 / 이 말이 있으면 금액이 아닌 칸
MONEY_HEADER = re.compile(rf"\(\s*원\s*\)|^(?:{AMOUNT_LABEL})$")
COUNT_HEADER = re.compile(r"수량|개수|인원|건수|횟수|사용량|량|번호|No|쪽|기간|일자|날짜|구분|항목")
UNIT_WON = re.compile(r"단위\s*[:：]?\s*원")
TABLE_NUMBER = re.compile(rf"^(?:{_NUM})$")

# 결과 쪽에서 번호를 찾을 때: 숫자와 - 로 이루어진 덩어리
NUMBER_RUN = re.compile(r"\d[\d\-]*\d|\d")


@dataclass
class Item:
    kind: str    # 종류 (날짜, 금액, 전화번호, 계좌번호, 고지번호 …)
    value: str   # 원문에 적힌 그대로의 값
    key: tuple   # 모양을 맞춘 비교용 값


@dataclass
class CheckResult:
    checked: list = field(default_factory=list)          # 검사한 중요 정보 (원문에서 뽑은 것)
    missing: list = field(default_factory=list)          # 결과에 빠진 중요 정보
    result_checked: list = field(default_factory=list)   # 역방향: 검사한 결과의 중요 정보
    invented: list = field(default_factory=list)         # 역방향: 원문에 없는 결과의 정보 (지어낸 값)
    year_added: list = field(default_factory=list)       # 역방향: 원문에 없던 연도가 붙었지만 월·일이 같아 통과한 날짜

    @property
    def ok(self):
        """빠진 정보가 없으면 True (기존 검사)"""
        return not self.missing

    @property
    def all_ok(self):
        """빠진 정보도, 원문에 없는 정보도 없으면 True"""
        return not self.missing and not self.invented

    @property
    def anything_checked(self):
        return bool(self.checked or self.result_checked)


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


def _table_amounts(text):
    """" | "로 나뉜 표에서 금액 칸의 숫자를 찾습니다. (위치, Item) 목록을 돌려줍니다.
    금액 칸: 머리글이 "금액(원)"·"금액"처럼 생긴 칸, 또는 "(단위: 원)" 아래 표에서 수량·인원 같은 칸이 아닌 칸"""
    found, offset = [], 0
    money_columns, unit_won, in_table = None, False, False
    for line in text.split("\n"):
        if UNIT_WON.search(line):
            unit_won = True
        if "|" not in line:
            if in_table:
                money_columns, unit_won, in_table = None, False, False
            offset += len(line) + 1
            continue
        cells = [cell.strip() for cell in line.split("|")]
        if not in_table:  # 표의 첫 줄 = 머리글
            in_table = True
            money_columns = [
                i for i, cell in enumerate(cells)
                if MONEY_HEADER.search(cell) or (unit_won and cell and not COUNT_HEADER.search(cell))
            ]
        else:
            for i in money_columns:
                if i < len(cells) and TABLE_NUMBER.match(cells[i]) and len(re.sub(r"\D", "", cells[i])) >= 3:
                    position = offset + line.find(cells[i])
                    found.append((position, Item("금액", cells[i], ("금액", _amount_value(cells[i])))))
        offset += len(line) + 1
    return found


def extract(text):
    """글에서 중요 정보를 원문 순서대로 뽑습니다. 같은 값은 한 번만 넣습니다."""
    work = text
    for pattern in (SKIP_LABELED, LAW_ARTICLE, PAGE_NUMBER):
        work = _blank(work, pattern)

    found = []  # (위치, Item)

    def take(pattern, make, blank_all=True):
        """모양에 맞는 부분을 찾아 중요 정보로 만들고, 다음 규칙이 다시 보지 않게 빈칸으로 바꿉니다.
        blank_all=False면 중요 정보가 된 부분만 빈칸으로 바꿉니다."""
        nonlocal work
        taken = []
        for m in pattern.finditer(work):
            item = make(m)
            if item is not None:
                found.append((m.start(), item))
                taken.append(m.span())
        if blank_all:
            work = _blank(work, pattern)
        else:
            for start, end in taken:
                work = work[:start] + re.sub(r"[^\n]", " ", work[start:end]) + work[end:]

    # 1) 이름표가 붙은 번호를 먼저 (전화·계좌 모양이어도 이 종류로 봅니다)
    take(LABELED_NUMBER, lambda m: Item(re.sub(r"\s", "", m.group(1)), m.group(2), ("번호", _digits(m.group(2)))))

    # 2) 날짜
    def full_date(m):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return Item("날짜", m.group(0).strip(), ("날짜", y, mo, d)) if _valid_date(mo, d) else None

    take(DATE_FULL, full_date)
    take(DATE_DOTTED, full_date)
    def short_year_date(m):
        yy, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        year = 2000 + yy if yy < 70 else 1900 + yy
        return Item("날짜", m.group(0).strip(), ("날짜", year, mo, d)) if _valid_date(mo, d) else None

    take(DATE_SHORT_YEAR, short_year_date)
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

    take(AMOUNT, amount, blank_all=False)  # "금액(원)" 머리글의 '원'은 표 금액을 찾을 때 써야 하므로 남깁니다.
    # "원" 없이 적힌 표 금액: 금액 이름표 뒤 숫자 → 금액 머리글 칸의 숫자
    take(LABELED_AMOUNT, lambda m: Item("금액", m.group(2), ("금액", _amount_value(m.group(2)))))
    table_items = _table_amounts(work)
    found.extend(table_items)
    for position, item in table_items:
        work = work[:position] + " " * len(item.value) + work[position + len(item.value):]

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


def _number_keys(items):
    """뽑은 정보 중 번호(전화·계좌·이름표 번호)의 숫자만 모읍니다. (055) 000-1111처럼 나뉜 번호도 한 덩어리로 봅니다."""
    return {item.key[1] for item in items if item.key[0] == "번호"}


def _date_anywhere(text, month, day):
    """글 어디에든 같은 월·일이 어떤 모양으로든 있는지 봅니다. (10월 20일, 10. 20., 10/20, 10-20)
    원문의 연도 없는 날짜처럼 중요 정보 뽑기 규칙이 알아보지 못하는 모양까지 넉넉하게 찾습니다."""
    pattern = rf"(?<![\d.])0?{month}\s*(?:월|[./\-])\s*0?{day}(?!\d)"
    return re.search(pattern, text) is not None


def _in_original(item, original, original_items, original_numbers):
    """결과의 정보 하나가 원문에 있는지 봅니다. (있음, 연도가 새로 붙음) 두 값을 돌려줍니다."""
    kind = item.key[0]
    if kind == "날짜":
        _, year, month, day = item.key
        same_day = [o.key for o in original_items if o.key[0] == "날짜" and o.key[2:] == (month, day)]
        if year is None:
            return bool(same_day) or _date_anywhere(original, month, day), False
        if any(k[1] == year for k in same_day):
            return True, False
        if any(k[1] is None for k in same_day) or (not same_day and _date_anywhere(original, month, day)):
            return True, True   # 원문에는 연도가 없는데 결과에 연도가 붙음
        return False, False
    if kind == "금액":
        return item.key in {o.key for o in original_items}, False
    return item.key[1] in original_numbers, False


def check(masked_original, result):
    """가린 원문과 결과를 두 방향으로 대조합니다."""
    # 1) 빠진 정보 (기존 검사, 그대로)
    checked = extract(masked_original)
    result_items = extract(result)
    result_keys = {item.key for item in result_items}
    result_numbers = {_digits(run) for run in NUMBER_RUN.findall(result)} | _number_keys(result_items)
    missing = [item for item in checked if not _present(item, result_keys, result_numbers)]

    # 2) 원문에 없는 정보 (역방향). 결과 전체([어려운 말 풀이] 포함)를 검사합니다.
    original_numbers = {_digits(run) for run in NUMBER_RUN.findall(masked_original)} | _number_keys(checked)
    invented, year_added = [], []
    for item in result_items:
        found, new_year = _in_original(item, masked_original, checked, original_numbers)
        if not found:
            invented.append(item)
        elif new_year:
            year_added.append(item)

    return CheckResult(checked=checked, missing=missing,
                       result_checked=result_items, invented=invented, year_added=year_added)


def missing_report(check_result):
    """빠진 정보를 사람이 읽을 목록 글로 만듭니다. 빠진 게 없으면 빈 글."""
    if not check_result or check_result.ok:
        return ""
    lines = ["[확인 필요] 원문에 있는데 결과에 빠진 정보"]
    lines += [f"- {item.kind}: {item.value}" for item in check_result.missing]
    return "\n".join(lines)


def invented_report(check_result):
    """원문에 없는 정보를 사람이 읽을 목록 글로 만듭니다. 없으면 빈 글."""
    if not check_result or not check_result.invented:
        return ""
    lines = ["[확인 필요] 원문에 그대로 적혀 있지 않은 값 (AI가 계산하거나 새로 쓴 값일 수 있으니 원문과 비교해 확인하세요)"]
    lines += [f"- {item.kind}: {item.value}" for item in check_result.invented]
    return "\n".join(lines)


def problems_report(check_result):
    """내려받는 파일 맨 아래에 붙일 [확인 필요] 글. 문제가 없으면 빈 글."""
    return "\n\n".join(part for part in (missing_report(check_result), invented_report(check_result)) if part)
