"""Claude API 연결이 잘 되는지 확인합니다.

사용법:
    python test_connection.py
"""

import os
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv

MODEL = "claude-sonnet-5"
TEST_MESSAGE = "안녕하세요 연결 테스트입니다"

BASE_DIR = Path(__file__).resolve().parent


def main():
    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit(
            "[실패] API 키가 없습니다.\n"
            "프로젝트 폴더에 .env 파일이 있는지, 그 안에 ANTHROPIC_API_KEY=... 줄이 있는지 확인하세요."
        )

    print(f"보내는 말: {TEST_MESSAGE}")
    print(f"모델: {MODEL}\n")

    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": TEST_MESSAGE}],
        )
    except anthropic.AuthenticationError:
        sys.exit(
            "[실패] API 키가 틀렸습니다.\n"
            "키를 복사할 때 앞뒤 글자가 빠지거나 공백이 들어가지 않았는지 확인하세요."
        )
    except anthropic.PermissionDeniedError:
        sys.exit("[실패] 이 API 키로는 이 기능을 쓸 권한이 없습니다. Claude Console에서 키 권한을 확인하세요.")
    except anthropic.NotFoundError:
        sys.exit(f"[실패] 모델 이름을 찾을 수 없습니다: {MODEL}\n모델 이름에 오타가 없는지 확인하세요.")
    except anthropic.RateLimitError:
        sys.exit("[실패] 짧은 시간에 요청이 너무 많았습니다. 1분쯤 기다린 뒤 다시 실행하세요.")
    except anthropic.BadRequestError as e:
        if "credit" in str(e.message).lower():
            sys.exit("[실패] 크레딧(사용 금액)이 부족합니다. Claude Console의 결제(Billing) 메뉴에서 충전하세요.")
        sys.exit(f"[실패] 요청 내용에 문제가 있습니다.\n자세한 내용: {e.message}")
    except anthropic.APIStatusError as e:
        if e.status_code >= 500:
            sys.exit(f"[실패] Claude 서버에 일시적인 문제가 있습니다 (오류 번호 {e.status_code}). 잠시 뒤 다시 실행하세요.")
        sys.exit(f"[실패] 알 수 없는 API 오류입니다 (오류 번호 {e.status_code}).\n자세한 내용: {e.message}")
    except anthropic.APIConnectionError:
        sys.exit("[실패] Claude 서버에 연결하지 못했습니다. 인터넷 연결을 확인하세요.")

    answer = "".join(block.text for block in response.content if block.type == "text")
    print(f"Claude의 답변:\n{answer}\n")
    print("[성공] 연결이 잘 됩니다!")


if __name__ == "__main__":
    main()
