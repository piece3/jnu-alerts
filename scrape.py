# -*- coding: utf-8 -*-
"""
전남대 전자컴퓨터공학부 통합 알림 수집기
  - 각 소스 게시판을 긁어 data.json 저장
  - template.html + data.json  ->  dashboard.html (자체 완결 파일) 생성
  - 한 소스가 실패하면 직전 data.json 값을 재사용하고 'stale' 표시
사용:  python scrape.py
"""
import sys, io, json, time, hashlib, traceback
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

import sources as S

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
requests.packages.urllib3.disable_warnings()

HERE = Path(__file__).resolve().parent
DATA_JSON = HERE / "data.json"
TEMPLATE = HERE / "template.html"
DASHBOARD = HERE / "dashboard.html"
LOG = HERE / "last_run.log"

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"}
TODAY = date.today()
NEW_DAYS = 4          # first_seen 이후 며칠까지 'NEW' 뱃지
KEEP_PER_SOURCE = 30  # 소스별 저장 최대 건수

_loglines = []
def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line)
    _loglines.append(line)


# ── 분류 ────────────────────────────────────────────────────
CAT_RULES = [
    ("job",      ("채용", "인턴", "취업", "현장실습", "정규직", "계약직", "리크루팅", "채용연계")),
    ("contest",  ("공모전", "경진대회", "해커톤", "챌린지", "콘테스트", "대회", "아이디어 경진",
                  "hackathon", "challenge")),
    ("academic", ("장학", "학자금", "학사", "수강신청", "수강", "등록금", "등록 ", "졸업", "학위",
                  "성적", "복수전공", "부전공", "계절학기", "휴학", "복학")),
]
def categorize(title):
    t = title.lower()
    for cat, kws in CAT_RULES:
        for kw in kws:
            if kw.lower() in t:
                return cat
    return "notice"


# ── 마감일 추출 ─────────────────────────────────────────────
import re
_P_FULL = re.compile(r"~\s*(\d{4})[.\s]*(\d{1,2})[.\s]*(\d{1,2})")
_P_MD   = re.compile(r"~\s*(\d{1,2})\s*[./월]\s*(\d{1,2})")
_P_KO   = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일\s*까지")

def _mk(y, m, d):
    try:
        return date(y, m, d)
    except ValueError:
        return None

def _resolve_md(m, d):
    y = TODAY.year
    if m < TODAY.month - 6:      # 한참 지난 달이면 내년 마감
        y += 1
    return _mk(y, m, d)

def extract_deadline(title):
    c = []
    for mo in _P_FULL.finditer(title):
        c.append(_mk(int(mo[1]), int(mo[2]), int(mo[3])))
    for mo in _P_MD.finditer(title):
        c.append(_resolve_md(int(mo[1]), int(mo[2])))
    for mo in _P_KO.finditer(title):
        c.append(_resolve_md(int(mo[1]), int(mo[2])))
    c = [x for x in c if x and (TODAY - timedelta(days=1)) <= x <= (TODAY + timedelta(days=400))]
    return min(c).isoformat() if c else None


# ── 수집 ────────────────────────────────────────────────────
def fetch(src):
    r = requests.get(src["url"], headers=UA, timeout=25, verify=False)
    r.raise_for_status()
    parser = S.PARSERS[src["kind"]]
    items = parser(r, src)
    # 정리: 제목 없는 것 제외, 중복 url 제거
    seen, clean = set(), []
    for it in items:
        u = it.get("url", "").strip()
        t = (it.get("title") or "").strip()
        if not u or not t or u in seen:
            continue
        seen.add(u)
        it["title"] = re.sub(r"\s+", " ", t)
        clean.append(it)
    return clean


def load_prev():
    if not DATA_JSON.exists():
        return {}, {}
    try:
        prev = json.loads(DATA_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    first_seen, by_source = {}, {}
    for s in prev.get("sources", []):
        by_source[s["key"]] = s
        for it in s.get("items", []):
            if it.get("url") and it.get("first_seen"):
                first_seen[it["url"]] = it["first_seen"]
    return first_seen, by_source


def sort_items(items):
    # 고정공지 먼저(날짜 내림차순), 그다음 일반글 날짜 내림차순
    return sorted(
        items,
        key=lambda it: (0 if it.get("pinned") else 1, _neg_date(it.get("date"))),
    )

def _neg_date(d):
    try:
        return -datetime.strptime(d, "%Y-%m-%d").toordinal()
    except Exception:
        return 0


def main():
    first_seen, prev_by_source = load_prev()
    out_sources = []
    todays = TODAY.isoformat()

    for src in S.SOURCES:
        entry = dict(key=src["key"], name=src["name"], url=src["url"],
                     kind=src["kind"], stale=False, error=None, items=[])

        if src["kind"] == "linkonly":
            entry["linkonly"] = True
            log(f"{src['key']:9s}  (링크 전용, 수집 안 함)")
            out_sources.append(entry)
            continue

        try:
            items = fetch(src)
            if not items:
                raise RuntimeError("파싱 결과 0건 (사이트 구조 변경 의심)")
            for it in items:
                it["source"] = src["key"]
                it["id"] = hashlib.md5(it["url"].encode("utf-8")).hexdigest()[:10]
                it["category"] = src.get("force_cat") or categorize(it["title"])
                it["deadline"] = extract_deadline(it["title"])
                if it["deadline"] and it["date"]:   # 오래된 글의 마감 표기는 신뢰도↓
                    try:
                        if (TODAY - date.fromisoformat(it["date"])).days > 120:
                            it["deadline"] = None
                    except ValueError:
                        pass
                fs = first_seen.get(it["url"], todays)
                it["first_seen"] = fs
                try:
                    recent_seen = (TODAY - date.fromisoformat(fs)).days <= NEW_DAYS
                except ValueError:
                    recent_seen = False
                try:  # 첫 실행에서 몇 달 된 글에 NEW가 붙지 않도록 글 날짜도 확인
                    fresh_post = (not it["date"]) or (TODAY - date.fromisoformat(it["date"])).days <= 21
                except ValueError:
                    fresh_post = True
                it["is_new"] = recent_seen and fresh_post
            entry["items"] = sort_items(items)[:KEEP_PER_SOURCE]
            log(f"{src['key']:9s}  {len(entry['items']):3d}건  "
                f"(신규 {sum(1 for i in entry['items'] if i['is_new'])})")
        except Exception as e:
            prev = prev_by_source.get(src["key"], {})
            entry["items"] = prev.get("items", [])
            entry["stale"] = True
            entry["error"] = f"{type(e).__name__}: {e}"
            log(f"{src['key']:9s}  실패 -> 직전 데이터 유지 ({entry['error']})")
        out_sources.append(entry)
        time.sleep(0.6)

    payload = dict(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        schedule="매일 08시·18시 자동 갱신",
        total=sum(len(s["items"]) for s in out_sources),
        sources=out_sources,
    )
    DATA_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"data.json 저장 (총 {payload['total']}건)")

    tpl = TEMPLATE.read_text(encoding="utf-8")
    html = tpl.replace("/*__DATA__*/", "window.DASH_DATA = "
                       + json.dumps(payload, ensure_ascii=False) + ";")
    DASHBOARD.write_text(html, encoding="utf-8")
    log(f"dashboard.html 생성 완료")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("치명적 오류:\n" + traceback.format_exc())
    finally:
        LOG.write_text("\n".join(_loglines) + "\n", encoding="utf-8")
