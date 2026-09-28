"""어려운 공문서를 쉬운 한국어로 바꿔 저장합니다.

텍스트 파일: 이름·주소 찾기 → 개인정보 가리기 → 쉬운 한국어 변환 순서로 처리합니다.
사진 파일: 사진 준비 → 원문 복원(이름·주소 표시 포함) → 개인정보 가리기 → 쉬운 한국어 변환 순서로 처리합니다.

사용법:
    python convert.py test_notice.txt
    python convert.py notice_photo.jpg
"""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from image_prep import SUPPORTED_EXTENSIONS, ImageError, prepare_image
from mark_personal import MarkError, mark_personal
from redact import redact
from transcribe import TranscribeError, transcribe

MODEL = "claude-sonnet-5"

BASE_DIR = Path(__file__).resolve().parent
RULES_FILE = BASE_DIR / "prompts" / "rules.txt"
SAMPLES_DIR = BASE_DIR / "samples"
RESULTS_DIR = SAMPLES_DIR / "results"


def find_input_file(name):
    """samples 폴더 안의 파일 이름이나 파일 경로를 받아 실제 파일 위치를 찾습니다."""
    for candidate in (SAMPLES_DIR / name, Path(name)):
        if candidate.is_file():
            return candidate
    sys.exit(f"파일을 찾을 수 없습니다: {name}\nsamples 폴더에 있는 .txt 파일이나 사진 파일 이름을 입력하세요.")


def convert(client, rules, original_text):
    """규칙서와 원문을 Claude에게 보내 쉬운 한국어 결과를 받아옵니다."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=rules,
        messages=[
            {
                "role": "user",
                "content": f"다음 문서를 규칙에 맞게 쉬운 한국어로 바꿔 주세요.\n\n<원문>\n{original_text}\n</원문>",
            }
        ],
    )

    if response.stop_reason == "refusal":
        sys.exit("AI가 이 문서의 변환을 거절했습니다. 문서 내용을 확인해 주세요.")

    result = "".join(block.text for block in response.content if block.type == "text")

    if response.stop_reason == "max_tokens":
        result += "\n\n(주의: 결과가 너무 길어 중간에 잘렸습니다. 원문 확인 필요)"
    return result


def read_photo(client, input_file):
    """사진에서 원문을 복원하고 개인정보를 가린 글을 돌려줍니다. 가리기 전 글은 저장하지 않습니다."""
    print("[1/4] 사진 준비 중 (방향 바로잡기, 크기 줄이기)")
    media_type, image_data = prepare_image(input_file)

    print("[2/4] 원문 복원 중 (사진 속 글자 읽기, 이름·주소 표시)")
    marked_text = transcribe(client, media_type, image_data)

    print("[3/4] 개인정보 가리는 중")
    return hide_personal_info(marked_text)


def read_text(client, input_file):
    """txt 파일에서 이름·주소를 찾아 표시한 뒤 개인정보를 가린 글을 돌려줍니다. 가리기 전 글은 저장하지 않습니다."""
    text = input_file.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(f"파일이 비어 있습니다: {input_file}")

    print("[1/3] 이름·주소 찾는 중")
    marked_text = mark_personal(client, text)

    print("[2/3] 개인정보 가리는 중")
    return hide_personal_info(marked_text)


def hide_personal_info(marked_text):
    masked_text, counts = redact(marked_text)
    if counts:
        print("      가린 개인정보: " + ", ".join(f"{label} {n}개" for label, n in counts.items()))
    else:
        print("      가린 개인정보: 없음")
    return masked_text


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python convert.py <samples 폴더 안의 파일 이름>\n예시: python convert.py test_notice.txt")

    input_file = find_input_file(sys.argv[1])
    suffix = input_file.suffix.lower()
    is_photo = suffix in SUPPORTED_EXTENSIONS
    if suffix != ".txt" and not is_photo:
        sys.exit(
            f"지원하지 않는 파일 형식입니다: {input_file.suffix or '(확장자 없음)'}\n"
            "txt 파일이나 jpg, jpeg, png, heic 사진을 넣어 주세요."
        )

    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("API 키가 없습니다. .env.example을 복사해 .env 파일을 만들고 키를 넣어 주세요.")

    rules = RULES_FILE.read_text(encoding="utf-8")
    client = anthropic.Anthropic()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    try:
        original_text = read_photo(client, input_file) if is_photo else read_text(client, input_file)
        original_file = RESULTS_DIR / f"{input_file.stem}_original.txt"
        original_file.write_text(original_text + "\n", encoding="utf-8")
        print(f"      저장했습니다: {original_file}")
        print("[4/4] 쉬운 한국어로 바꾸는 중" if is_photo else "[3/3] 쉬운 한국어로 바꾸는 중")

        result = convert(client, rules, original_text)
    except (ImageError, TranscribeError, MarkError) as e:
        sys.exit(f"\n[멈춤] {e}")
    except anthropic.AuthenticationError:
        sys.exit("API 키가 올바르지 않습니다. .env 파일의 ANTHROPIC_API_KEY를 확인하세요.")
    except anthropic.RateLimitError:
        sys.exit("요청이 너무 많습니다. 잠시 후 다시 실행하세요.")
    except anthropic.APIStatusError as e:
        sys.exit(f"API 오류가 났습니다 ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("인터넷 연결을 확인하세요.")

    output_file = RESULTS_DIR / f"{input_file.stem}_result.txt"
    output_file.write_text(result + "\n", encoding="utf-8")

    print()
    print(result)
    print(f"\n저장했습니다: {output_file}")


if __name__ == "__main__":
    main()
