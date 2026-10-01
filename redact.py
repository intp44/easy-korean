"""3단계: 개인정보 가리기

1) AI가 붙여 둔 [[이름:…]], [[주소:…]] 표시를 찾아 가립니다. (홍길동 → 홍○○, 주소 → 시·군·구까지만)
2) 주민등록번호, 카드번호, 휴대폰 번호, 계좌번호를 찾아 *로 가립니다.
3) AI가 표시를 빠뜨렸을 때를 대비해 "성명:", "주소:" 같은 글자 뒤의 이름·주소를 한 번 더 가립니다.
AI를 쓰지 않고 정해진 규칙(정규식)으로만 처리하므로 같은 글을 넣으면 결과가 항상 같습니다.

가리지 않는 것 (문의·납부에 필요한 정보):
- 기관 전화번호(1588-0000, 02-000-0000 같은 번호), 기관 이름과 주소, 담당자 이름
- 납부번호·고지번호·고객번호·전자납부번호 (휴대폰 번호 모양이어도 가리지 않음)
- 가상계좌·납부계좌·입금계좌처럼 기관에 돈을 내는 계좌 (환급·지급·수령·본인 계좌나 이름표 없는 계좌는 가림)
"""

import re

# 숫자 앞뒤에 다른 숫자가 붙어 있지 않을 때만 찾습니다. (한글 바로 옆에 붙은 번호도 찾기 위해 \b 대신 사용)
_START = r"(?<!\d)"
_END = r"(?!\d)"
_SEP = r"[ \-.]?"

# 주민등록번호·외국인등록번호: 900101-1234567 → 900101-1******
RRN = re.compile(
    _START + r"(\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(\s*-\s*|\s?)([1-8])\d{6}" + _END
)

# 카드번호: 1234-5678-9012-3456 → 1234-****-****-****
CARD = re.compile(_START + r"(\d{4})([ \-])\d{4}\2\d{4}\2\d{3,4}" + _END)

# 휴대폰 번호: 010-1234-5678 → 010-****-****
MOBILE = re.compile(_START + r"(01[016789])(" + _SEP + r")\d{3,4}(" + _SEP + r")\d{4}" + _END)

# 계좌번호: 숫자 묶음 3~5개를 -로 이은 것 중 숫자가 모두 10~14자리인 것 → 첫 묶음만 남김
ACCOUNT = re.compile(_START + r"\d{2,6}(?:-\d{1,8}){2,4}" + _END)
# '계좌' 글자 바로 뒤에 오는 -없는 10~14자리 숫자도 계좌번호로 봅니다.
ACCOUNT_AFTER_WORD = re.compile(r"(계좌[^\d\n]{0,15})" + _START + r"(\d{10,14})" + _END)

# 지역번호 전화(02-000-0000, 031-000-0000, 070-0000-0000 등)는 계좌번호로 보지 않습니다.
LANDLINE = re.compile(r"0\d{1,2}-\d{3,4}-\d{4}")


# 이 이름표 바로 뒤에 오는 번호는 납부·문의에 필요하므로 가리지 않습니다.
PAYMENT_LABEL = re.compile(r"(?:전자납부번호|납부자번호|납부번호|고지번호|고객번호)\s*[:：|]?\s*$")


def _after_payment_label(match):
    """번호 바로 앞(같은 줄)에 '납부번호:' 같은 이름표가 있는지 봅니다."""
    line_start = match.string.rfind("\n", 0, match.start()) + 1
    return PAYMENT_LABEL.search(match.string[line_start : match.start()]) is not None


# 계좌번호 앞 이름표. 기관에 돈을 내는 계좌는 남기고, 사용자 본인 계좌는 가립니다.
PAYMENT_ACCOUNT_LABEL = r"가상\s?계좌|납부\s?계좌|입금\s?계좌|납부할\s?계좌|납부하실\s?계좌|입금할\s?계좌|입금하실\s?계좌"
PERSONAL_ACCOUNT_LABEL = r"환급|지급|수령|본인|예금주|받으실|받을"
ACCOUNT_LABEL = re.compile(f"(?P<keep>{PAYMENT_ACCOUNT_LABEL})|(?P<hide>{PERSONAL_ACCOUNT_LABEL})")
# 이름표와 번호 사이에 다른 번호가 끼어 있으면, 그 이름표는 이 번호의 것이 아닐 수 있습니다.
OTHER_NUMBER = re.compile(r"\d{2,}-\d|\d{8,}")


def _is_payment_account(text, number_start):
    """계좌번호 바로 앞(같은 줄과 윗줄)에서 가장 가까운 이름표가 '가상계좌' 같은 납부용 이름표인지 봅니다.
    이름표가 없거나, 본인 계좌 이름표이거나, 애매하면 False(가림)를 돌려줍니다."""
    line_start = text.rfind("\n", 0, number_start) + 1
    previous_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
    before = text[previous_line_start:number_start]

    labels = list(ACCOUNT_LABEL.finditer(before))
    if not labels:
        return False
    nearest = labels[-1]
    between = before[nearest.end():]
    return nearest.group("keep") is not None and not OTHER_NUMBER.search(between)


def _star_digits(text):
    return re.sub(r"\d", "*", text)


# 이 말이 번호 앞(같은 줄과 윗줄)에 있으면 계좌 이름표가 있어도 주민번호로 보고 가립니다.
RRN_WORDS = re.compile(r"주민|외국인|등록\s?번호|생년월일")


def _is_payment_account_not_rrn(match):
    """'-' 없이 붙은 13자리 숫자가 주민번호 모양이어도, 바로 앞에 '가상계좌' 같은 납부용 이름표가 있으면
    계좌번호로 봅니다. 이름표가 없거나 애매하면 False(주민번호로 가림)."""
    if match.group(2):   # 900101-1234567처럼 나뉜 번호는 계좌 모양이 아니므로 늘 주민번호로 봅니다.
        return False
    text, start = match.string, match.start()
    line_start = text.rfind("\n", 0, start) + 1
    previous_line_start = text.rfind("\n", 0, max(0, line_start - 1)) + 1
    if RRN_WORDS.search(text[previous_line_start:start]):
        return False
    return _is_payment_account(text, start)


def _mask_rrn(match):
    if _is_payment_account_not_rrn(match):
        return match.group(0)   # 아래 계좌번호 규칙이 다시 판단합니다.
    return f"{match.group(1)}{match.group(2)}{match.group(3)}******"


def _mask_card(match):
    first, sep = match.group(1), match.group(2)
    return first + sep + _star_digits(match.group(0)[len(first) + 1 :])


def _mask_mobile(match):
    return match.group(1) + _star_digits(match.group(0)[len(match.group(1)) :])


def _mask_account(match):
    number = match.group(0)
    digit_count = sum(c.isdigit() for c in number)
    if not 10 <= digit_count <= 14 or LANDLINE.fullmatch(number) or _looks_like_date(number):
        return number
    if _is_payment_account(match.string, match.start()):
        return number
    first, rest = number.split("-", 1)
    return first + "-" + _star_digits(rest)


def _mask_account_after_word(match):
    number = match.group(2)
    if _is_payment_account(match.string, match.start(2)):
        return match.group(0)
    return match.group(1) + number[:3] + "*" * (len(number) - 3)


def _looks_like_date(number):
    """2026-10-20-1234처럼 날짜로 시작하는 문서번호는 계좌번호로 보지 않습니다."""
    return re.match(r"(19|20)\d{2}-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])(?!\d)", number) is not None


# 순서가 중요합니다. 모양이 분명한 번호부터 먼저 가립니다.
_RULES = [
    ("주민등록번호", RRN, _mask_rrn),
    ("카드번호", CARD, _mask_card),
    ("휴대폰 번호", MOBILE, _mask_mobile),
    ("계좌번호", ACCOUNT, _mask_account),
    ("계좌번호", ACCOUNT_AFTER_WORD, _mask_account_after_word),
]


# ── 이름·주소 ──────────────────────────────────────────

# AI가 붙인 표시: [[이름:홍길동]], [[주소:…]]. 닫는 괄호가 하나 빠져도 찾습니다.
MARKER = re.compile(r"\[\[\s*(이름|주소)\s*[:：]\s*([^\]\n]*?)\s*\]\]?")

# 두 글자 성씨. 이 성씨로 시작하는 세 글자 이상 이름은 두 글자를 남깁니다. (남궁민 → 남궁○)
COMPOUND_SURNAMES = ("남궁", "황보", "제갈", "선우", "독고", "사공", "서문")

# 글자 규칙으로 이름을 찾을 때, 이 성씨로 시작해야 이름으로 봅니다. ("보호자 동의" 같은 말을 이름으로 착각하지 않도록)
COMMON_SURNAMES = set(
    # 흔한 성씨만 넣었습니다. '동', '시', '상'처럼 보통 낱말 첫 글자로 자주 쓰이는 드문 성씨는 뺐습니다.
    "김이박최정강조윤장임한오서신권황안송류유전홍고문양손배백허남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위"
) | set(COMPOUND_SURNAMES)

# 이름으로 보지 않을 말
NOT_A_NAME = {"참조", "귀하", "없음", "본인", "담당자", "미상", "생략", "기재", "해당", "동의"}
# 이 말로 끝나면 사람이 아니라 기관으로 봅니다.
ORGANIZATION_ENDINGS = ("청", "과", "팀", "센터", "공단", "공사", "은행", "회사", "협회", "학교", "병원", "시장", "군수", "청장", "귀중")

# 주소에서 남길 시·도 줄임말
PROVINCES = {
    "서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기", "강원",
    "충북", "충남", "전북", "전남", "경북", "경남", "제주",
}
REGION_ENDINGS = ("특별시", "광역시", "특별자치시", "특별자치도", "도", "시", "군", "구")

# 이 말이 주소 줄이나 바로 윗줄에 있으면 기관 주소로 보고 가리지 않습니다.
INSTITUTION_WORDS = (
    "방문", "오시는", "찾아오시는", "청사", "민원실", "기관", "센터", "접수처", "제출처", "문의", "위치",
    "시청", "구청", "군청", "도청", "우체국", "공단",
)

_LINE_HEAD = r"^[ \t]*(?:[-·*•]\s*|\d+[.)]\s*|[가-하][.)]\s*)?"
_NAME_LABEL = r"(?:받는\s?분|수신[자인]?|성\s?명|이름|보호자(?:\s?성명)?|납부자(?:\s?성명)?)"
_NAME_VALUE = r"([가-힣]{2,4}?)(?=$|[\s,.(·|)]|귀하|님|씨|께)"

# "성명: 홍길동", "수신자 | 홍길동"처럼 이름표 뒤에 : 나 | 가 있는 경우 (줄 어디서나)
LABELED_NAME = re.compile(r"(?<![가-힣])(" + _NAME_LABEL + r")(?!번호)(\s*[:：|]\s*)" + _NAME_VALUE, re.M)
# "수신자 홍길동 귀하"처럼 줄 맨 앞 이름표 뒤에 띄어쓰기만 있는 경우
LINE_START_NAME = re.compile("(" + _LINE_HEAD + _NAME_LABEL + r")(?!번호)(\s+)" + _NAME_VALUE, re.M)

# "주소: …"로 시작하는 줄. 줄 끝까지를 주소로 봅니다.
_ADDRESS_LABEL = r"(?:(?:받는\s?분|수신자|보호자|납부자|본인)\s?)?(?:주\s?소지?|거주지)"
LABELED_ADDRESS = re.compile("(" + _LINE_HEAD + _ADDRESS_LABEL + r")(\s*[:：|]\s*|\s+)(\S.*)$", re.M)


def mask_name(name):
    """성만 남깁니다. 홍길동(洪吉童) → 홍○○"""
    name = re.sub(r"\s*\(.*?\)", "", name).replace(" ", "")
    if not name:
        return "○○○"
    keep = 2 if name[:2] in COMPOUND_SURNAMES and len(name) >= 3 else 1
    return name[:keep] + "○" * max(1, len(name) - keep)


def mask_address(address):
    """시·군·구까지만 남깁니다. 경남 창원시 ○○로 12, 101동 → 경남 창원시 ○○○"""
    kept = []
    for word in address.split():
        is_region = word in PROVINCES or (
            len(word) >= 2 and re.fullmatch(r"[가-힣]+", word) and word.endswith(REGION_ENDINGS)
        )
        if not is_region or len(kept) == 3:
            break
        kept.append(word)
    return " ".join(kept + ["○○○"])


def _mask_marker(match):
    label, value = match.group(1), match.group(2)
    return mask_name(value) if label == "이름" else mask_address(value)


def _looks_like_person(name):
    return (
        name[0] in COMMON_SURNAMES or name[:2] in COMPOUND_SURNAMES
    ) and name not in NOT_A_NAME and not name.endswith(ORGANIZATION_ENDINGS)


def _mask_labeled_name(match):
    label, sep, name = match.group(1), match.group(2), match.group(3)
    if not _looks_like_person(name):
        return match.group(0)
    return label + sep + mask_name(name)


def _looks_like_address(value):
    words = value.split()
    return any(w in PROVINCES or re.search(r"[가-힣](시|도|군|구|로|길|동|읍|면)$", w) for w in words)


def _mask_labeled_address(match):
    label, sep, value = match.group(1), match.group(2), match.group(3)
    line_start = match.start()
    previous_line = match.string[match.string.rfind("\n", 0, max(0, line_start - 1)) + 1 : line_start]
    if (
        "○" in value
        or not _looks_like_address(value)
        or any(word in label + value + previous_line for word in INSTITUTION_WORDS)
    ):
        return match.group(0)
    return label + sep + mask_address(value)


_NAME_ADDRESS_RULES = [
    ("이름 (글자 규칙)", LABELED_NAME, _mask_labeled_name),
    ("이름 (글자 규칙)", LINE_START_NAME, _mask_labeled_name),
    ("주소 (글자 규칙)", LABELED_ADDRESS, _mask_labeled_address),
]


def _apply(text, rules, counts, skip_payment_numbers=False):
    for label, pattern, mask in rules:
        def replace(match, label=label, mask=mask):
            if skip_payment_numbers and label != "주민등록번호" and _after_payment_label(match):
                return match.group(0)
            masked = mask(match)
            if masked != match.group(0):
                counts[label] = counts.get(label, 0) + 1
            return masked

        text = pattern.sub(replace, text)
    return text


def redact(text):
    """개인정보를 가린 글과, 종류별로 몇 개를 가렸는지 담은 목록을 돌려줍니다."""
    counts = {}

    def replace_marker(match):
        label = f"{match.group(1)} (AI 표시)"
        counts[label] = counts.get(label, 0) + 1
        return _mask_marker(match)

    text = MARKER.sub(replace_marker, text)
    text = _apply(text, _RULES, counts, skip_payment_numbers=True)
    text = _apply(text, _NAME_ADDRESS_RULES, counts)
    return text, counts
