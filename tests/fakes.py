"""가짜 Claude 응답 (진짜 API 대신 씁니다)"""

from types import SimpleNamespace


def text_block(text):
    return SimpleNamespace(type="text", text=text)


def tool_block(name, value):
    return SimpleNamespace(type="tool_use", name=name, input=value)


class FakeMessages:
    def __init__(self, client):
        self.client = client

    def create(self, **kwargs):
        self.client.calls.append(kwargs)
        return SimpleNamespace(content=self.client.blocks, stop_reason=self.client.stop_reason)

    def stream(self, **kwargs):
        self.client.calls.append(kwargs)
        return FakeStream(self.client)


class FakeStream:
    """글 조각을 하나씩 내보내다가, fail_after 개를 보낸 뒤 오류를 낼 수 있습니다."""

    def __init__(self, client):
        self.client = client

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        for i, piece in enumerate(self.client.pieces):
            if self.client.fail_after is not None and i == self.client.fail_after:
                raise self.client.error
            yield piece
        if self.client.fail_after is not None and self.client.fail_after >= len(self.client.pieces):
            raise self.client.error

    def get_final_message(self):
        return SimpleNamespace(stop_reason=self.client.stop_reason)


class FakeClient:
    """messages.create / messages.stream 을 흉내 냅니다. 부른 기록은 calls에 남습니다."""

    def __init__(self, blocks=None, stop_reason="end_turn", pieces=None, fail_after=None, error=None):
        self.blocks = blocks or []
        self.stop_reason = stop_reason
        self.pieces = pieces or []
        self.fail_after = fail_after
        self.error = error
        self.calls = []
        self.messages = FakeMessages(self)
