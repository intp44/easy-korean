"""전체 처리 흐름

터미널(convert.py)과 나중에 만들 화면(Streamlit)이 함께 불러 쓰는 부분입니다.

순서:
1. 원문 준비 (사진이면 원문 복원, 글이면 이름·주소 찾기) → 개인정보 가리기
   - prepare_original: 컴퓨터에 있는 파일로 준비 (터미널용)
   - prepare_photo / prepare_text: 메모리에 있는 사진·글로 준비 (화면용, 파일을 만들지 않음)
   이 단계는 끝까지 다 만든 다음 넘겨줍니다. 가리기 전 글이 먼저 보이면 안 되기 때문입니다.
2. EasyKoreanStream: 가린 원문을 쉬운 한국어로 바꾸며 조각을 하나씩 내보냅니다.
   끝까지 성공하면 결과를 원문과 대조 검증(verify_result)합니다.
   저장할 파일을 알려준 경우(터미널)에만 _result.txt로 저장하고, 중간에 오류가 나면 아무것도 저장하지 않습니다.
3. explain_error: 어떤 오류든 쉬운 한국어 설명으로 바꿉니다.
"""

from pathlib import Path

import anthropic

from image_prep import SUPPORTED_EXTENSIONS, ImageError, prepare_image
from mark_personal import MarkError, mark_personal
from redact import redact
from simplify import ConvertError, MaskedText, stream_easy_korean
from transcribe import TranscribeError, transcribe
from verify import check

RESULTS_DIR = Path(__file__).resolve().parent / "samples" / "results"

# 사진 한 장의 최대 용량입니다. 이보다 크면 처리하지 않고 쉬운 말로 알려줍니다.
MAX_PHOTO_MB = 20


class InputError(Exception):
    """넣은 파일에 문제가 있을 때 쓰는 오류입니다. 메시지는 사용자에게 그대로 보여줍니다."""


def is_photo(input_file):
    return input_file.suffix.lower() in SUPPORTED_EXTENSIONS


def check_input_file(input_file):
    """처리할 수 있는 파일(txt 또는 사진)인지 확인합니다."""
    if input_file.suffix.lower() != ".txt" and not is_photo(input_file):
        raise InputError(
            f"지원하지 않는 파일 형식입니다: {input_file.suffix or '(확장자 없음)'}\n"
            "txt 파일이나 jpg, jpeg, png, heic 사진을 넣어 주세요."
        )


def prepare_original(client, input_file, report=print):
    """컴퓨터에 있는 파일로 원문을 준비하고 개인정보를 가린 글(MaskedText)을 돌려줍니다. (터미널용)
    report: 진행 상황 문장을 받을 함수입니다. 터미널은 print, 화면은 화면에 글을 쓰는 함수를 넘기면 됩니다."""
    check_input_file(input_file)
    if is_photo(input_file):
        return prepare_photo(client, input_file.name, input_file.read_bytes(), report)
    return prepare_text(client, input_file.read_text(encoding="utf-8"), report, source=input_file.name)


def prepare_photo(client, name, data, report=print):
    """메모리에 있는 사진(바이트)으로 원문을 복원하고 개인정보를 가린 글을 돌려줍니다. 파일을 만들지 않습니다.
    name: 사진 파일 이름 (확장자로 형식을 확인합니다)"""
    if len(data) > MAX_PHOTO_MB * 1024 * 1024:
        raise InputError(
            f"사진 용량이 너무 커요 ({len(data) / 1024 / 1024:.0f}MB). {MAX_PHOTO_MB}MB보다 작은 사진을 올려 주세요.\n"
            "폰 카메라 설정에서 사진 크기를 줄이거나, 화면을 캡처해서 올려도 돼요."
        )
    report("[1/4] 사진 준비 중 (방향 바로잡기, 크기 줄이기)")
    media_type, image_data = prepare_image(Path(name), data=data)
    report("[2/4] 원문 복원 중 (사진 속 글자 읽기, 이름·주소 표시)")
    marked_text = transcribe(client, media_type, image_data)
    report("[3/4] 개인정보 가리는 중")
    return _hide_personal_info(marked_text, report)


def prepare_text(client, text, report=print, source="붙여 넣은 글"):
    """메모리에 있는 글로 이름·주소를 찾아 표시한 뒤 개인정보를 가린 글을 돌려줍니다. 파일을 만들지 않습니다."""
    text = text.strip()
    if not text:
        raise InputError(f"글이 비어 있습니다: {source}")
    report("[1/3] 이름·주소 찾는 중")
    marked_text = mark_personal(client, text)
    report("[2/3] 개인정보 가리는 중")
    return _hide_personal_info(marked_text, report)


def _hide_personal_info(marked_text, report):
    masked_text, counts = redact(marked_text)
    if counts:
        report("      가린 개인정보: " + ", ".join(f"{label} {n}개" for label, n in counts.items()))
    else:
        report("      가린 개인정보: 없음")
    return MaskedText(masked_text)


def convert_step_message(photo):
    """쉬운 한국어 변환 단계의 진행 상황 문장입니다."""
    return "[4/4] 쉬운 한국어로 바꾸는 중" if photo else "[3/3] 쉬운 한국어로 바꾸는 중"


def _original_path(input_file):
    return RESULTS_DIR / f"{input_file.stem}_original.txt"


def _result_path(input_file):
    return RESULTS_DIR / f"{input_file.stem}_result.txt"


def remove_old_results(input_file):
    """같은 이름으로 전에 만든 _original.txt와 _result.txt를 지웁니다. (터미널에서 새로 실행할 때)"""
    for path in (_original_path(input_file), _result_path(input_file)):
        path.unlink(missing_ok=True)


def save_original(input_file, masked_text):
    """가린 원문을 samples/results/원본파일이름_original.txt로 저장합니다."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _original_path(input_file)
    path.write_text(masked_text + "\n", encoding="utf-8")
    return path


def verify_result(masked_text, result):
    """원문과 결과 대조 검증

    가린 원문(masked_text)과 쉬운 한국어 결과(result)의 날짜·금액·전화번호·계좌번호·이름표가 붙은 번호를
    코드 규칙으로 두 방향 대조합니다. (자세한 규칙은 verify.py)
    돌려주는 값: .missing (결과에 빠진 정보), .invented (원문에 없는 정보),
                .year_added (원문에 없던 연도가 붙었지만 통과한 날짜), .all_ok (둘 다 문제없으면 True)
    """
    return check(masked_text, result)


class EasyKoreanStream:
    """쉬운 한국어 결과를 조각이 생길 때마다 하나씩 내보내고, 끝까지 성공하면 결과를 모읍니다.

    사용법:
        stream = EasyKoreanStream(client, masked_text)              # 화면용: 저장하지 않음
        stream = EasyKoreanStream(client, masked_text, input_file)  # 터미널용: _result.txt로 저장
        for piece in stream:
            (조각을 화면에 이어 붙여 보여주기)
        stream.result      # 완성된 전체 결과
        stream.saved_to    # 저장한 파일 위치 (저장하지 않았으면 None)
        stream.check       # 검증 결과 (.missing: 빠진 정보, .invented: 원문에 없는 정보)

    중간에 오류가 나면 for 문에서 오류가 나고, 아무것도 저장되지 않습니다.
    그때까지 보여준 조각은 완성된 결과가 아니므로 화면에서 지워야 합니다.
    """

    def __init__(self, client, masked_text, input_file=None):
        self.client = client
        self.masked_text = masked_text
        self.input_file = input_file
        self.result = None
        self.saved_to = None
        self.check = None

    def __iter__(self):
        pieces = []
        for piece in stream_easy_korean(self.client, self.masked_text):
            pieces.append(piece)
            yield piece

        # 여기까지 왔다면 변환이 끝까지 성공한 것입니다.
        result = "".join(pieces)
        self.check = verify_result(self.masked_text, result)
        if self.input_file is not None:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            self.saved_to = _result_path(self.input_file)
            self.saved_to.write_text(result + "\n", encoding="utf-8")
        self.result = result


def explain_error(error):
    """오류를 사용자에게 보여줄 쉬운 한국어 설명으로 바꿉니다."""
    if isinstance(error, (InputError, ImageError, TranscribeError, MarkError, ConvertError)):
        return str(error)
    if isinstance(error, anthropic.AuthenticationError):
        return "API 키가 올바르지 않습니다. 비밀 설정(Secrets)이나 .env 파일의 ANTHROPIC_API_KEY를 확인하세요."
    if isinstance(error, anthropic.RateLimitError):
        return "요청이 너무 많습니다. 잠시 후 다시 실행하세요."
    if isinstance(error, anthropic.APIStatusError):
        if error.status_code >= 500:
            return f"Claude 서버에 일시적인 문제가 있습니다 (오류 번호 {error.status_code}). 잠시 뒤 다시 실행하세요."
        return f"API 오류가 났습니다 ({error.status_code}): {error.message}"
    if isinstance(error, anthropic.APIConnectionError):
        return "Claude 서버에 연결하지 못했거나 연결이 끊겼습니다. 인터넷 연결을 확인하고 다시 실행하세요."
    return f"알 수 없는 오류가 났습니다: {error}"


# 화면이나 터미널이 오류를 잡을 때 쓰는 목록입니다.
KNOWN_ERRORS = (InputError, ImageError, TranscribeError, MarkError, ConvertError, anthropic.APIError)
