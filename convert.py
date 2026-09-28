"""어려운 공문서를 쉬운 한국어로 바꿔 저장합니다. (터미널용)

텍스트 파일: 이름·주소 찾기 → 개인정보 가리기 → 쉬운 한국어 변환 순서로 처리합니다.
사진 파일: 사진 준비 → 원문 복원(이름·주소 표시 포함) → 개인정보 가리기 → 쉬운 한국어 변환 순서로 처리합니다.
쉬운 한국어 결과는 만들어지는 대로 조금씩 화면에 나옵니다.
실제 처리 흐름은 pipeline.py에 있습니다.

사용법:
    python convert.py test_notice.txt
    python convert.py notice_photo.jpg
"""

import os
import sys
import time
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from pipeline import (
    KNOWN_ERRORS,
    EasyKoreanStream,
    check_input_file,
    convert_step_message,
    explain_error,
    is_photo,
    prepare_original,
    remove_old_results,
    save_original,
)

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"


def find_input_file(name):
    """samples 폴더 안의 파일 이름이나 파일 경로를 받아 실제 파일 위치를 찾습니다."""
    for candidate in (SAMPLES_DIR / name, Path(name)):
        if candidate.is_file():
            return candidate
    sys.exit(f"파일을 찾을 수 없습니다: {name}\nsamples 폴더에 있는 .txt 파일이나 사진 파일 이름을 입력하세요.")


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python convert.py <samples 폴더 안의 파일 이름>\n예시: python convert.py test_notice.txt")

    input_file = find_input_file(sys.argv[1])
    try:
        check_input_file(input_file)
    except KNOWN_ERRORS as e:
        sys.exit(explain_error(e))

    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("API 키가 없습니다. .env.example을 복사해 .env 파일을 만들고 키를 넣어 주세요.")

    client = anthropic.Anthropic()
    started = time.perf_counter()

    # 실패했을 때 옛 결과가 남아 헷갈리지 않도록, 같은 이름의 옛 결과 파일을 먼저 지웁니다.
    remove_old_results(input_file)

    # 1) 원문 준비와 개인정보 가리기: 끝까지 다 만든 다음 넘겨받습니다.
    try:
        masked_text = prepare_original(client, input_file, report=print)
    except KNOWN_ERRORS as e:
        sys.exit(f"\n[멈춤] {explain_error(e)}")
    print(f"      저장했습니다: {save_original(input_file, masked_text)}")

    # 2) 쉬운 한국어 변환: 만들어지는 대로 조금씩 보여줍니다.
    print(convert_step_message(is_photo(input_file)))
    print()
    convert_started = time.perf_counter()
    first_piece_at = None
    stream = EasyKoreanStream(client, masked_text, input_file)
    try:
        for piece in stream:
            if first_piece_at is None:
                first_piece_at = time.perf_counter()
            print(piece, end="", flush=True)
    except KNOWN_ERRORS as e:
        sys.exit(
            f"\n\n[멈춤] {explain_error(e)}\n"
            "위에 나온 글은 완성되지 않은 결과라서 저장하지 않았습니다. 다시 실행해 주세요."
        )
    finished = time.perf_counter()

    print(f"\n\n저장했습니다: {stream.saved_to}")
    print("\n===== 걸린 시간")
    print(f"전체: {finished - started:.1f}초")
    if first_piece_at is not None:
        print(
            f"첫 글자까지: {first_piece_at - started:.1f}초 (처음부터) / "
            f"{first_piece_at - convert_started:.1f}초 (변환 단계 시작부터)"
        )


if __name__ == "__main__":
    main()
