"""개인정보 가리기 (redact.py)

모든 이름·주소·번호는 가짜입니다.
"""

import pytest

from redact import mask_address, mask_name, redact


def hide(text):
    return redact(text)[0]


# ── 모양이 분명한 번호 ─────────────────────────────────
@pytest.mark.parametrize("text, expected", [
    ("주민등록번호: 900101-1234567", "주민등록번호: 900101-1******"),
    ("주민번호 900101 - 2234567", "주민번호 900101 - 2******"),
    ("외국인등록번호 9001015234567", "외국인등록번호 9001015******"),
])
def test_rrn(text, expected):
    assert hide(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("연락처: 010-1234-5678", "연락처: 010-****-****"),
    ("휴대폰 01012345678", "휴대폰 010********"),
    ("전화 010 1234 5678로", "전화 010 **** ****로"),
    ("보호자010-9876-5432", "보호자010-****-****"),  # 한글 바로 옆에 붙은 번호
])
def test_mobile(text, expected):
    assert hide(text) == expected


@pytest.mark.parametrize("text, expected", [
    ("카드번호: 1234-5678-9012-3456", "카드번호: 1234-****-****-****"),
    ("결제카드 1234 5678 9012 3456", "결제카드 1234 **** **** ****"),
])
def test_card(text, expected):
    assert hide(text) == expected


def test_account_without_label_is_hidden():
    assert hide("가상은행 110-123-456789") == "가상은행 110-***-******"


# ── AI가 붙인 이름·주소 표시 ───────────────────────────
def test_name_marker():
    assert hide("수신: [[이름:홍길동]] 님") == "수신: 홍○○ 님"


def test_compound_surname_marker():
    assert hide("[[이름:남궁가상]]") == "남궁○○"


def test_address_marker_keeps_city_only():
    assert hide("[[주소:경상남도 가상시 의창구 가상로 12, 101동 202호]]") == "경상남도 가상시 의창구 ○○○"


def test_marker_with_missing_bracket():
    assert hide("[[이름:홍길동] 귀하") == "홍○○ 귀하"


def test_marker_counts():
    _, counts = redact("[[이름:홍길동]] [[주소:부산광역시 가상구 가상로 1]] 010-1234-5678")
    assert counts == {"이름 (AI 표시)": 1, "주소 (AI 표시)": 1, "휴대폰 번호": 1}


def test_mask_name_and_address_helpers():
    assert mask_name("홍길동(洪吉童)") == "홍○○"
    assert mask_name("") == "○○○"
    assert mask_address("서울 가상구 가상로 5") == "서울 가상구 ○○○"


# ── 이름표 뒤 이름·주소 (AI가 표시를 빠뜨렸을 때) ───────
@pytest.mark.parametrize("text, expected", [
    ("성명: 김가상", "성명: 김○○"),
    ("수신자 | 박가상", "수신자 | 박○○"),
    ("수신자 이가상 귀하", "수신자 이○○ 귀하"),
    ("납부자: 최가상", "납부자: 최○○"),
    ("보호자 성명: 정가상", "보호자 성명: 정○○"),
])
def test_labeled_name(text, expected):
    assert hide(text) == expected


def test_labeled_address():
    assert hide("주소: 경상남도 가상시 의창구 가상로 12") == "주소: 경상남도 가상시 의창구 ○○○"


def test_resident_address_label():
    assert hide("거주지 부산광역시 가상구 가상동 1-2") == "거주지 부산광역시 가상구 ○○○"


# ── 가리면 안 되는 것 ─────────────────────────────────
@pytest.mark.parametrize("text", [
    "문의: 가상구청 교통행정과 051-000-1234",       # 기관 전화
    "고객센터 1588-0000",                            # 대표번호
    "수어 영상상담 070-0000-1111",                    # 인터넷 전화
    "수신자: 가상구청장",                             # 기관 이름
    "받는 분: 가상건강보험공단",                       # 기관 이름
    "담당자: 교통행정과 이가상 주무관 (051-000-1234)",  # 담당자 이름
    "성명: 본인",                                     # 이름이 아닌 말
])
def test_institution_info_is_kept(text):
    assert hide(text) == text


@pytest.mark.parametrize("text", [
    "고객번호: 010-4567-8910",            # 휴대폰 모양이어도 고객번호
    "납부번호: 01098765432",
    "전자납부번호: 0123-1-26090012345",
    "고지번호: 2026-0912-000123",
])
def test_payment_numbers_are_kept(text):
    assert hide(text) == text


@pytest.mark.parametrize("text", [
    "방문 장소: 가상시청 민원실\n주소: 경상남도 가상시 의창구 중앙대로 151",
    "오시는 길 주소: 부산광역시 가상구 중앙대로 151",
])
def test_institution_address_is_kept(text):
    assert hide(text) == text


def test_already_masked_address_is_left_alone():
    text = "주소: 부산광역시 가상구 ○○○"
    assert hide(text) == text


def test_same_text_same_result():
    text = "성명: 김가상\n연락처: 010-1234-5678\n주소: 서울특별시 가상구 가상로 1"
    assert hide(text) == hide(text)
