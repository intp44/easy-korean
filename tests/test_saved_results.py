"""예전에 만든 결과 파일로 검증 규칙 확인 (내 컴퓨터에서만)

samples 폴더는 개인정보 보호를 위해 git에 올리지 않으므로, 이 폴더가 없는 컴퓨터에서는 건너뜁니다.
검증 규칙을 바꾼 뒤에도 진짜 AI가 만든 예전 결과에 "원문에 없는 값" 경고가 잘못 뜨지 않는지 봅니다.
"""

from pathlib import Path

import pytest

from verify import check

RESULTS_DIR = Path(__file__).resolve().parent.parent / "samples" / "results"
PAIRS = [
    (path, path.with_name(path.name.replace("_original.txt", "_result.txt")))
    for path in sorted(RESULTS_DIR.glob("*_original.txt"))
]


@pytest.mark.skipif(not PAIRS, reason="samples/results 폴더가 없습니다 (git에 올리지 않는 폴더)")
@pytest.mark.parametrize("original, result", PAIRS, ids=[p[0].stem for p in PAIRS])
def test_no_false_invented_warning(original, result):
    if not result.exists():
        pytest.skip("결과 파일 없음")
    found = check(original.read_text(encoding="utf-8"), result.read_text(encoding="utf-8"))
    assert found.invented == []
