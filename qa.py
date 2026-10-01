"""문서에 대해 묻고 답하기 (에이전트 2단계)

쉬운 한국어 결과를 본 사용자가 문서에 대해 더 물어볼 수 있게 합니다.
지시문은 prompts/qa.txt에 있습니다.

- 모델은 claude-haiku-4-5. 질문 한 번에 AI 호출 1번, 문서 한 건당 질문은 5번까지입니다.
  AI 호출이 실패한 질문은 횟수에서 빼고, 다음 질문 때 AI에게 보내지도 않습니다.
- AI에게 보내는 것: 가린 원문 + 쉬운 한국어 결과 + 이 문서의 이전 질문·답변(성공한 것만) + 새 질문
- 사용자가 쓴 질문도 AI에게 보내기 전에 redact.py로 가립니다. (질문 가리기에는 AI를 쓰지 않습니다)
- 답이 끝나면 verify.py의 역방향 검사로, 답에 나온 날짜·금액·전화번호·계좌번호가
  원문이나 질문에 있는지 확인합니다. 둘 다에 없는 값은 화면에 경고합니다.
- 질문과 답은 화면 상태(메모리)에만 두고, 어디에도 저장하지 않습니다.
"""

from dataclasses import dataclass, field
from pathlib import Path

from redact import redact
from simplify import MaskedText
from verify import check

MODEL = "claude-haiku-4-5"
PROMPT_FILE = Path(__file__).resolve().parent / "prompts" / "qa.txt"
MAX_QUESTIONS = 5
MAX_ANSWER_TOKENS = 1000

# 처음에 누르기만 하면 되는 예시 질문. AI가 만들지 않고 코드에 고정합니다.
EXAMPLE_QUESTIONS = [
    "이 문서에서 제일 중요한 게 뭐예요?",
    "제가 꼭 해야 하는 일이 있나요?",
    "어려운 말을 더 쉽게 알려주세요",
]
FAILED_ANSWER = "답을 불러오지 못했어요. 다시 물어봐 주세요"
NO_MORE_QUESTIONS = "더 궁금한 건 담당자에게 문의해 주세요"
TRUNCATED_NOTE = "\n(답이 길어서 중간에 잘렸어요)"


class QAError(Exception):
    """답을 끝까지 받지 못했을 때 쓰는 오류입니다."""


def mask_question(question):
    """질문 속 개인정보를 기존 가리기 규칙(번호, 이름표 뒤 이름·주소)으로 가립니다."""
    return redact(question.strip())[0]


def unknown_values(masked_original, masked_question, answer):
    """답에 나온 날짜·금액·전화번호·계좌번호 중 원문에도 질문에도 없는 값을 돌려줍니다.
    verify.py의 역방향 검사(원문에 없는 값 찾기)를 원문과 질문에 한 번씩 써서, 둘 다에서 걸린 값만 남깁니다."""
    not_in_original = check(masked_original, answer).invented
    if not not_in_original:
        return []
    not_in_question = {item.key for item in check(masked_question, answer).invented}
    return [item.value for item in not_in_original if item.key in not_in_question]


def unknown_warning(values):
    """답 바로 아래에 보여줄 경고 글. 문제없으면 빈 글."""
    if not values:
        return ""
    return f"⚠️ 이 답에 문서에 없는 값({', '.join(values)})이 있어요. 원문을 확인하세요"


@dataclass
class Turn:
    question: str            # 가린 질문 (화면에도 이것만 보여줍니다)
    answer: str = ""
    unknown: list = field(default_factory=list)   # 원문에도 질문에도 없는 값
    failed: bool = False     # 답을 불러오지 못한 질문 (횟수에서 빼고, AI에게 다시 보내지 않음)


class Conversation:
    """문서 한 건의 질문·답변 기록입니다. 새 문서를 바꾸면 화면이 이 기록을 통째로 버립니다.

    사용법:
        conversation = Conversation(masked_text, result)
        for piece in conversation.ask(client, "언제까지 가야 해요?"):
            (조각을 화면에 이어 붙여 보여주기)
        conversation.turns[-1]   # 방금 질문과 답 (실패했으면 failed=True)
    """

    def __init__(self, masked_original, result):
        if not isinstance(masked_original, MaskedText):
            raise TypeError("개인정보를 가린 원문(MaskedText)으로만 묻고 답하기를 할 수 있습니다.")
        self.masked_original = masked_original
        self.result = result
        self.turns = []

    @property
    def used(self):
        return sum(1 for turn in self.turns if not turn.failed)

    @property
    def remaining(self):
        return max(0, MAX_QUESTIONS - self.used)

    def messages_for(self, masked_question):
        """AI에게 보낼 대화. 첫 질문에 문서 두 개를 붙이고, 성공한 이전 질문·답변을 차례로 넣습니다."""
        document = f"<원문>\n{self.masked_original}\n</원문>\n\n<쉬운결과>\n{self.result}\n</쉬운결과>\n\n"
        questions = [turn for turn in self.turns if not turn.failed] + [Turn(masked_question)]
        messages = []
        for i, turn in enumerate(questions):
            messages.append({"role": "user", "content": (document if i == 0 else "") + f"<질문>\n{turn.question}\n</질문>"})
            if i < len(questions) - 1:
                messages.append({"role": "assistant", "content": turn.answer})
        return messages

    def ask(self, client, question):
        """질문을 가린 뒤 답을 조각으로 하나씩 내보냅니다. 끝까지 받으면 기록에 남기고 값을 확인합니다.
        중간에 실패하면 실패한 질문으로 기록하고(횟수에서 뺌) QAError를 냅니다.
        질문을 다 썼으면 QAError를 내고 AI를 부르지 않습니다."""
        if self.remaining == 0:
            raise QAError(NO_MORE_QUESTIONS)
        masked_question = mask_question(question)
        messages = self.messages_for(masked_question)
        # 끝까지 받기 전에는 실패로 적어 둡니다. 화면이 중간에 끊겨도 횟수에 들어가지 않게 하기 위해서입니다.
        turn = Turn(masked_question, failed=True)
        self.turns.append(turn)
        pieces = []
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_ANSWER_TOKENS,
                system=PROMPT_FILE.read_text(encoding="utf-8"),
                messages=messages,
            ) as stream:
                for piece in stream.text_stream:
                    pieces.append(piece)
                    yield piece
                final = stream.get_final_message()
            if final.stop_reason in (None, "refusal"):
                raise QAError(f"답이 끝나지 않았습니다 ({final.stop_reason}).")
            if final.stop_reason == "max_tokens":
                pieces.append(TRUNCATED_NOTE)
                yield TRUNCATED_NOTE
            answer = "".join(pieces).strip()
            if not answer:
                raise QAError("빈 답을 받았습니다.")
        except QAError:
            raise
        except Exception as error:   # 인터넷 끊김, API 오류 등
            raise QAError(str(error)) from error

        turn.answer = answer
        turn.failed = False
        turn.unknown = unknown_values(self.masked_original, masked_question, answer)
