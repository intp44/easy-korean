"""모든 테스트에 공통으로 적용되는 준비

- 진짜 Claude API를 절대 부르지 않도록, 테스트 중에는 인터넷 요청 자체를 막습니다.
  AI가 필요한 부분은 tests/fakes.py의 가짜 응답을 씁니다.
- 테스트 데이터는 모두 가짜 이름·주소·번호입니다. (이 폴더는 GitHub에 올라갑니다)
"""

import httpx
import pytest


@pytest.fixture(autouse=True)
def no_real_api(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def blocked(*args, **kwargs):
        raise RuntimeError("테스트 중에는 진짜 인터넷 요청(Claude API)을 보낼 수 없습니다. 가짜 응답을 쓰세요.")

    monkeypatch.setattr(httpx.Client, "send", blocked)
    monkeypatch.setattr(httpx.AsyncClient, "send", blocked)
