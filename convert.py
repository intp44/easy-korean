"""어려운 공문서 텍스트 파일을 쉬운 한국어로 바꿔 저장합니다.

사용법:
    python convert.py test_notice.txt
"""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

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
    sys.exit(f"파일을 찾을 수 없습니다: {name}\nsamples 폴더에 있는 .txt 파일 이름을 입력하세요.")


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


def main():
    if len(sys.argv) != 2:
        sys.exit("사용법: python convert.py <samples 폴더 안의 파일 이름>\n예시: python convert.py test_notice.txt")

    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("API 키가 없습니다. .env.example을 복사해 .env 파일을 만들고 키를 넣어 주세요.")

    input_file = find_input_file(sys.argv[1])
    original_text = input_file.read_text(encoding="utf-8").strip()
    if not original_text:
        sys.exit(f"파일이 비어 있습니다: {input_file}")

    rules = RULES_FILE.read_text(encoding="utf-8")

    print(f"변환 중입니다: {input_file.name} (잠시 기다려 주세요)")
    client = anthropic.Anthropic()
    try:
        result = convert(client, rules, original_text)
    except anthropic.AuthenticationError:
        sys.exit("API 키가 올바르지 않습니다. .env 파일의 ANTHROPIC_API_KEY를 확인하세요.")
    except anthropic.RateLimitError:
        sys.exit("요청이 너무 많습니다. 잠시 후 다시 실행하세요.")
    except anthropic.APIStatusError as e:
        sys.exit(f"API 오류가 났습니다 ({e.status_code}): {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("인터넷 연결을 확인하세요.")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output_file = RESULTS_DIR / f"{input_file.stem}_result.txt"
    output_file.write_text(result + "\n", encoding="utf-8")

    print(result)
    print(f"\n저장했습니다: {output_file}")


if __name__ == "__main__":
    main()
