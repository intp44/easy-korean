"""계획서 성능 목표 측정 스크립트 (터미널용)

측정하는 것
  - 처리 시간: 단계별(원문 준비 / 첫 결과 표시 / 변환 완료 / 도움 고르기)과 전체
  - 문장 길이: 원문과 쉬운 결과의 평균 문장 길이(공백 뺀 글자 수)와 단축률
  - 핵심 정보 추출 정확도: samples/answers.csv(정답표)가 있으면 [해야 할 일]과 비교

사용법
  python measure.py           # samples 폴더의 문서를 실제 AI로 처리 (API 비용 발생, 실행 전 확인)
  python measure.py --saved   # 이미 저장된 samples/results 로 문장 길이만 계산 (비용 없음)

정답표 samples/answers.csv 형식 (첫 줄은 머리글, 없는 항목은 "없음", 여러 개면 ; 로 구분)
  파일,기한,장소,금액,준비물
  notice01.jpg,2026. 10. 20.,가상은행 900-0000-0000-01,"32,000원",없음

결과
  samples/results/measure_results.csv  (문서별 결과, 엑셀로 열기)
  화면에 요약 출력
"""

import csv
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"
RESULTS_DIR = SAMPLES_DIR / "results"
ANSWERS = SAMPLES_DIR / "answers.csv"
FIELDS = ["기한", "장소", "금액", "준비물"]
TIME_GOAL = 15.0


# ── 문장 길이 ─────────────────────────────────────────
def sentences(text):
    """줄바꿈과 '. ? !' 뒤에서 문장을 나눕니다. 제목([해야 할 일] 등)과 빈 줄은 뺍니다."""
    parts = re.split(r"\n+|(?<=[.!?])\s+", text)
    out = []
    for p in parts:
        p = p.strip().lstrip("-•· ").strip()
        if not p or re.fullmatch(r"\[.*\]", p):
            continue
        out.append(p)
    return out


def avg_len(text):
    s = sentences(text)
    if not s:
        return 0.0
    return sum(len(re.sub(r"\s", "", x)) for x in s) / len(s)


def easy_part(result):
    """문장 길이는 [쉬운 설명] 부분으로 잽니다. 없으면 결과 전체."""
    m = re.search(r"\[쉬운 설명\](.*?)(\n\[|\Z)", result, re.S)
    return m.group(1) if m else result


def todo_part(result):
    m = re.search(r"\[해야 할 일\](.*?)(\n\[|\Z)", result, re.S)
    return m.group(1) if m else result


# ── 정확도 ────────────────────────────────────────────
def norm(t):
    return re.sub(r"[\s,]", "", t)


def load_answers():
    if not ANSWERS.exists():
        return {}
    with ANSWERS.open(encoding="utf-8-sig") as f:
        return {unicodedata.normalize("NFC", row["파일"].strip()): row for row in csv.DictReader(f)}


def score(answer_row, result):
    """정답표의 항목 값이 [해야 할 일]에 들어 있는지 셉니다. (맞은 수, 전체 수, 틀린 항목)"""
    todo = norm(todo_part(result))
    hit = total = 0
    misses = []
    for field in FIELDS:
        value = (answer_row.get(field) or "").strip()
        if not value or value == "없음":
            continue
        for item in [v.strip() for v in value.split(";") if v.strip()]:
            total += 1
            if norm(item) in todo:
                hit += 1
            else:
                misses.append(f"{field}:{item}")
    return hit, total, misses


# ── 실제 처리 ─────────────────────────────────────────
def run_one(client, path):
    from agent import choose_help
    from pipeline import EasyKoreanStream, prepare_original

    t0 = time.perf_counter()
    masked = prepare_original(client, path, report=lambda _m: None)
    t_prep = time.perf_counter() - t0

    stream = EasyKoreanStream(client, masked)
    first = None
    for _piece in stream:
        if first is None:
            first = time.perf_counter() - t0
    t_convert = time.perf_counter() - t0

    choose_help(client, masked, stream.result)
    t_total = time.perf_counter() - t0
    return {
        "original": str(masked), "result": stream.result, "check": stream.check,
        "원문준비(초)": t_prep, "첫결과표시(초)": first or t_convert,
        "변환완료(초)": t_convert, "전체(초)": t_total,
    }


def sample_files():
    exts = {".txt", ".jpg", ".jpeg", ".png", ".heic"}
    return sorted(p for p in SAMPLES_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts and p.name != "answers.csv")


def saved_pairs():
    """samples/results 의 _original.txt / _result.txt 짝을 찾습니다."""
    pairs = []
    for orig in sorted(RESULTS_DIR.glob("*_original.txt")):
        res = orig.with_name(orig.name.replace("_original.txt", "_result.txt"))
        if res.exists():
            pairs.append((orig.name.replace("_original.txt", ""), orig.read_text(encoding="utf-8"), res.read_text(encoding="utf-8")))
    return pairs


def summarize(rows):
    n = len(rows)
    if not n:
        print("측정한 문서가 없습니다.")
        return
    print(f"\n===== 요약 ({n}건) =====")
    o = sum(r["원문 평균 문장 길이"] for r in rows) / n
    e = sum(r["결과 평균 문장 길이"] for r in rows) / n
    print(f"평균 문장 길이: 원문 {o:.1f}자 → 결과 {e:.1f}자 (단축률 {(1 - e / o) * 100 if o else 0:.0f}%, 목표 50% 이상)")
    timed = [r for r in rows if r.get("전체(초)") not in (None, "")]
    if timed:
        tot = [float(r["전체(초)"]) for r in timed]
        first = [float(r["첫결과표시(초)"]) for r in timed]
        within = sum(t <= TIME_GOAL for t in tot)
        print(f"처리 시간: 전체 평균 {sum(tot) / len(tot):.1f}초 (최소 {min(tot):.1f} / 최대 {max(tot):.1f}), "
              f"{TIME_GOAL:.0f}초 이내 {within}/{len(tot)}건, 첫 결과 표시 평균 {sum(first) / len(first):.1f}초")
    scored = [r for r in rows if r.get("정답 항목 수")]
    if scored:
        hit = sum(int(r["맞은 항목 수"]) for r in scored)
        tot = sum(int(r["정답 항목 수"]) for r in scored)
        print(f"핵심 정보 추출 정확도: {hit}/{tot} = {hit / tot * 100:.0f}% (목표 90% 이상, 정답표 있는 {len(scored)}건)")
        print("  ※ 글자 그대로 비교라 표기만 다른 정답은 틀림으로 셀 수 있어요. CSV의 '놓친 항목'을 사람이 한 번 확인하세요.")
    else:
        print("핵심 정보 추출 정확도: samples/answers.csv(정답표)가 없어 계산하지 않았습니다.")


def write_csv(rows):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "measure_results.csv"
    keys = []
    for r in rows:
        for k in r:
            if k not in keys:
                keys.append(k)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\n문서별 결과: {out}")


def row_for(name, original, result, answers):
    name = unicodedata.normalize("NFC", name)  # 맥에서 한글 파일 이름이 자모 분리(NFD)되어도 정답표와 맞춥니다
    row = {
        "문서": name,
        "원문 평균 문장 길이": round(avg_len(original), 1),
        "결과 평균 문장 길이": round(avg_len(easy_part(result)), 1),
    }
    o, e = row["원문 평균 문장 길이"], row["결과 평균 문장 길이"]
    row["단축률(%)"] = round((1 - e / o) * 100) if o else ""
    if name in answers:
        hit, total, misses = score(answers[name], result)
        row.update({"맞은 항목 수": hit, "정답 항목 수": total, "놓친 항목": " / ".join(misses)})
    return row


def main():
    answers = load_answers()
    if "--saved" in sys.argv:
        pairs = saved_pairs()
        rows = []
        for stem, original, result in pairs:
            # 정답표의 파일 이름은 확장자를 포함하므로 같은 이름으로 시작하는 항목을 찾습니다.
            key = next((k for k in answers if Path(k).stem == stem), stem)
            rows.append(row_for(key, original, result, answers))
        write_csv(rows)
        summarize(rows)
        return

    import anthropic
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env", override=True)  # 셸에 남아 있는 옛 키보다 .env 키를 먼저 씁니다
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("API 키가 없습니다. .env 파일에 ANTHROPIC_API_KEY를 넣어 주세요.")
    files = sample_files()
    if not files:
        sys.exit("samples 폴더에 문서가 없습니다.")
    print(f"{len(files)}건을 실제 AI로 처리합니다. 문서 1건당 AI 호출 3번(사진) 또는 3번(글)이라 API 비용이 들어요.")
    if input("계속할까요? (y/n) ").strip().lower() != "y":
        sys.exit("취소했습니다.")
    client = anthropic.Anthropic()
    rows = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name} ...", end=" ", flush=True)
        try:
            r = run_one(client, path)
        except anthropic.AuthenticationError:
            sys.exit("\nAPI 키가 맞지 않아 멈춥니다 (AuthenticationError, 비용은 나가지 않았어요).\n"
                     ".env의 ANTHROPIC_API_KEY가 Anthropic 콘솔에서 유효한 키인지 확인해 주세요.")
        except Exception as e:  # 한 건이 실패해도 나머지는 계속
            print(f"실패 ({type(e).__name__})")
            rows.append({"문서": path.name, "오류": type(e).__name__})
            continue
        row = row_for(path.name, r["original"], r["result"], answers)
        for k in ("원문준비(초)", "첫결과표시(초)", "변환완료(초)", "전체(초)"):
            row[k] = round(r[k], 1)
        row["검증 경고"] = len(r["check"].missing) + len(r["check"].invented) if r["check"] else ""
        rows.append(row)
        print(f"{row['전체(초)']}초")
    ok = [r for r in rows if "오류" not in r]
    write_csv(rows)
    summarize(ok)


if __name__ == "__main__":
    main()
