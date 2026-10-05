"""계획서 성능 목표 측정 스크립트 (터미널용)

측정하는 것
  - 처리 시간: 단계별(원문 준비 / 첫 결과 표시 / 변환 완료 / 도움 고르기)과 전체
  - 문장 길이: 원문과 쉬운 결과의 평균 문장 길이(공백 뺀 글자 수)와 단축률
  - 핵심 정보 추출 정확도: samples/measure/answers.csv(정답표)가 있으면 결과와 비교
      기한·장소·금액은 결과의 [해야 할 일]에서, 준비물은 결과 전체에서 찾습니다.
      (변환 규칙서의 [해야 할 일]에는 준비물 칸이 없어서 준비물은 [쉬운 설명]에 쓰이기 때문입니다)

문장을 세는 기준 (원문과 쉬운 결과에 똑같이 적용합니다)
  - 원문은 문서 전체, 쉬운 결과는 [쉬운 설명] 부분을 잽니다.
  - 세지 않는 줄: 표 칸(| 로 나뉜 줄), 이름표 줄("고지번호: …", "담당자: …"처럼 짧은 이름 뒤에 : 이 오는 줄),
    제목 줄("[쉬운 설명]" 등), 빈 줄
  - 한 문장이 줄바꿈으로 끊겨 있으면(사진 속 글처럼) 다음 줄과 이어 붙입니다.
  - 문장은 "~다.", "~요.", "~오."(~하십시오), "?", "!" 뒤에서만 나눕니다. 그래서 날짜 속 점("2026. 11. 4.", "10. 20.")에서는 자르지 않습니다.
  - "~다.", "~요.", "~오.", "?", "!"로 끝나는 진짜 문장만 셉니다. 끝맺지 않은 조각은 세지 않습니다.
  - 문장 길이는 띄어쓰기를 뺀 글자 수입니다. 앞의 목록 기호("- ", "1.", "가.", "※")는 빼고 셉니다.
  - 진짜 문장이 하나도 없는 문서는 문장 길이 계산에서 빼고, 뺀 문서 수를 요약에 보여줍니다.

사용법
  python measure.py           # samples/measure 폴더의 문서를 실제 AI로 처리 (API 비용 발생, 실행 전 확인)
  python measure.py --saved   # 이미 저장된 samples/results 로 문장 길이만 계산 (비용 없음)

정답표 samples/measure/answers.csv 형식 (첫 줄은 머리글, 없는 항목은 "없음", 여러 개면 ; 로 구분)
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
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = BASE_DIR / "samples"
MEASURE_DIR = SAMPLES_DIR / "measure"          # 측정용 문서만 모아두는 폴더 (기존 테스트 파일과 분리)
RESULTS_DIR = SAMPLES_DIR / "results"
ANSWERS = MEASURE_DIR / "answers.csv"
FIELDS = ["기한", "장소", "금액", "준비물"]
TIME_GOAL = 15.0


# ── 문장 길이 ─────────────────────────────────────────
# 문장 끝: "~다." "~요." "~오."(하십시오) "?" "!" (뒤에 닫는 괄호·따옴표가 붙어도 됨)
SENTENCE_END = r"(?:[다요오]\.|[?!])[)」』\"'’”]*"
# 줄 맨 앞 목록 기호: "- ", "• ", "1. ", "2) ", "가. ", "※ "
LIST_MARK = re.compile(r"^(?:[-•·*※]\s*|\d{1,2}[.)]\s+|[가-하][.)]\s+)")
# 이름표 줄: 짧은 이름(띄어쓰기 포함 12자 이내) 뒤에 : 이 오는 줄. 예: "고지번호: …", "- 언제까지: …"
LABEL_LINE = re.compile(r"^[^\s:：][^:：]{0,11}[:：](?!\d)")   # "08:30"처럼 쌍점 뒤가 숫자면 시각이라 이름표 아님


def _skip_line(line):
    """세지 않는 줄: 표 칸, 이름표 줄, 제목 줄([쉬운 설명] 등)"""
    return "|" in line or LABEL_LINE.match(line) or re.fullmatch(r"\[.*\]", line)


def sentences(text):
    """진짜 문장만 골라 냅니다. (자세한 기준은 파일 맨 위 설명)"""
    chunks, current = [], ""
    for raw in text.split("\n"):
        line = LIST_MARK.sub("", raw.strip()).strip()
        starts_item = bool(LIST_MARK.match(raw.strip()))
        if not line or _skip_line(line):
            chunks.append(current)
            current = ""
            continue
        if starts_item or not current or re.search(SENTENCE_END + r"$", current):
            chunks.append(current)   # 목록의 새 항목이거나 앞 줄이 문장으로 끝났으면 새로 시작
            current = line
        else:
            current += " " + line    # 앞 줄이 끝맺지 않았으면 이어 붙임 (줄바꿈으로 끊긴 문장)
    chunks.append(current)

    # 앞에서부터 "문장 끝 + 띄어쓰기(또는 끝)"까지를 한 문장으로 잘라 냅니다. 끝맺지 않은 꼬리 조각은 버립니다.
    one_sentence = re.compile(r"\S.*?" + SENTENCE_END + r"(?=\s|$)")
    return [m.group(0).strip() for chunk in chunks for m in one_sentence.finditer(chunk.strip())]


def avg_len(text):
    """평균 문장 길이(띄어쓰기 뺀 글자 수). 진짜 문장이 없으면 None."""
    s = sentences(text)
    if not s:
        return None
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
        return {row["파일"].strip(): row for row in csv.DictReader(f)}


def score(answer_row, result):
    """정답표의 항목 값이 결과에 들어 있는지 셉니다.
    기한·장소·금액은 [해야 할 일]에서, 준비물은 결과 전체에서 찾습니다.
    돌려주는 값: (맞은 수, 전체 수, 틀린 항목, 항목별 {이름: (맞은 수, 전체 수)})"""
    todo, whole = norm(todo_part(result)), norm(result)
    hit = total = 0
    misses, by_field = [], {}
    for field in FIELDS:
        value = (answer_row.get(field) or "").strip()
        if not value or value == "없음":
            continue
        where = whole if field == "준비물" else todo
        field_hit = field_total = 0
        for item in [v.strip() for v in value.split(";") if v.strip()]:
            field_total += 1
            if norm(item) in where:
                field_hit += 1
            else:
                misses.append(f"{field}:{item}")
        by_field[field] = (field_hit, field_total)
        hit, total = hit + field_hit, total + field_total
    return hit, total, misses, by_field


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
    """samples/measure 폴더의 문서만 측정합니다. (기존 samples 폴더의 테스트 파일은 제외)"""
    if not MEASURE_DIR.exists():
        return []
    exts = {".txt", ".jpg", ".jpeg", ".png", ".heic"}
    return sorted(p for p in MEASURE_DIR.iterdir() if p.is_file() and p.suffix.lower() in exts)


def saved_pairs():
    """samples/results 의 _original.txt / _result.txt 짝을 찾습니다."""
    pairs = []
    for orig in sorted(RESULTS_DIR.glob("*_original.txt")):
        res = orig.with_name(orig.name.replace("_original.txt", "_result.txt"))
        if res.exists():
            pairs.append((orig.name.replace("_original.txt", ""), orig.read_text(encoding="utf-8"), res.read_text(encoding="utf-8")))
    return pairs


def summarize(rows, has_answers=True):
    n = len(rows)
    if not n:
        print("측정한 문서가 없습니다.")
        return
    print(f"\n===== 요약 ({n}건) =====")
    lengths = [r for r in rows if r["원문 평균 문장 길이"] != "" and r["결과 평균 문장 길이"] != ""]
    skipped = n - len(lengths)
    if lengths:
        o = sum(r["원문 평균 문장 길이"] for r in lengths) / len(lengths)
        e = sum(r["결과 평균 문장 길이"] for r in lengths) / len(lengths)
        print(f"평균 문장 길이: 원문 {o:.1f}자 → 결과 {e:.1f}자 (단축률 {(1 - e / o) * 100 if o else 0:.0f}%, 목표 50% 이상, "
              f"{len(lengths)}건 기준)")
    else:
        print("평균 문장 길이: 진짜 문장이 있는 문서가 없어 계산하지 않았습니다.")
    if skipped:
        print(f"  ※ 원문이나 결과에 진짜 문장(~다. ~요. ~오. ? !)이 하나도 없는 {skipped}건은 문장 길이 계산에서 뺐습니다.")
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
        for field in FIELDS:
            f_hit = sum(int(r.get(f"{field} 맞은 수") or 0) for r in scored)
            f_tot = sum(int(r.get(f"{field} 정답 수") or 0) for r in scored)
            where = "결과 전체에서 찾음" if field == "준비물" else "[해야 할 일]에서 찾음"
            print(f"  - {field}: {f_hit}/{f_tot}" + (f" = {f_hit / f_tot * 100:.0f}%" if f_tot else "") + f" ({where})")
        print("  ※ 글자 그대로 비교라 표기만 다른 정답은 틀림으로 셀 수 있어요. CSV의 '놓친 항목'을 사람이 한 번 확인하세요.")
    elif has_answers:
        print("핵심 정보 추출 정확도: 정답표는 있지만, 결과 중에 정답표에 적힌 측정 문서가 없어 계산하지 않았습니다.")
        print("  ※ --saved는 samples/results에 저장된 예전 결과로만 계산합니다. 측정 문서 결과는 python measure.py로 만듭니다.")
    else:
        print("핵심 정보 추출 정확도: samples/measure/answers.csv(정답표)가 없어 계산하지 않았습니다.")


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
    o, e = avg_len(original), avg_len(easy_part(result))
    row = {
        "문서": name,
        "원문 문장 수": len(sentences(original)),
        "원문 평균 문장 길이": round(o, 1) if o is not None else "",
        "결과 문장 수": len(sentences(easy_part(result))),
        "결과 평균 문장 길이": round(e, 1) if e is not None else "",
    }
    row["단축률(%)"] = round((1 - e / o) * 100) if o and e is not None else ""
    if name in answers:
        hit, total, misses, by_field = score(answers[name], result)
        row.update({"맞은 항목 수": hit, "정답 항목 수": total, "놓친 항목": " / ".join(misses)})
        for field in FIELDS:
            field_hit, field_total = by_field.get(field, (0, 0))
            row[f"{field} 맞은 수"], row[f"{field} 정답 수"] = field_hit, field_total
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
        summarize(rows, has_answers=bool(answers))
        return

    import anthropic
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("API 키가 없습니다. .env 파일에 ANTHROPIC_API_KEY를 넣어 주세요.")
    files = sample_files()
    if not files:
        sys.exit("samples/measure 폴더에 문서가 없습니다.")
    print(f"{len(files)}건을 실제 AI로 처리합니다. 문서 1건당 AI 호출 3번이라 API 비용이 들어요.")
    if input("계속할까요? (y/n) ").strip().lower() != "y":
        sys.exit("취소했습니다.")
    client = anthropic.Anthropic()
    rows = []
    for i, path in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {path.name} ...", end=" ", flush=True)
        try:
            r = run_one(client, path)
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
    summarize(ok, has_answers=bool(answers))  # 버그 수정: 예전엔 summarize(오케이)라서 마지막에 에러가 났음


if __name__ == "__main__":
    main()
