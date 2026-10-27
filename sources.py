# -*- coding: utf-8 -*-
"""
소스 정의 + 게시판 유형별 파서.
새 소스 추가/삭제는 아래 SOURCES 리스트만 고치면 된다.
각 파서는 표준 dict 리스트를 돌려준다:
    {"title","url","date"(YYYY-MM-DD 또는 ""),"pinned"(bool),"author"}
"""
import re
from urllib.parse import urljoin
from datetime import date, timedelta

from bs4 import BeautifulSoup

TODAY = date.today()

# ─────────────────────────────────────────────────────────────
# 소스 목록 (대시보드에 이 순서로 그룹이 생성됨)
# ─────────────────────────────────────────────────────────────
SOURCES = [
    dict(key="ece",      name="전자컴퓨터공학부",              kind="k2web",
         url="https://ece.jnu.ac.kr/bbs/ece/2770/artclList.do"),
    dict(key="eng",      name="공과대학 공지",                 kind="k2web",
         url="https://eng.jnu.ac.kr/bbs/eng/993/artclList.do"),
    dict(key="engjob",   name="공과대학 채용정보",              kind="k2web", force_cat="job",
         url="https://eng.jnu.ac.kr/bbs/eng/1287/artclList.do"),
    dict(key="jnu",      name="전남대 학사·일반공지",           kind="jnu",
         url="https://www.jnu.ac.kr/WebApp/web/HOM/COM/Board/board.aspx?boardID=5"),
    dict(key="sojoong",  name="소프트웨어중심대학 사업단",       kind="kboard",
         url="https://sojoong.kr/notice/notice-board/"),
    dict(key="aicoss",   name="인공지능혁신융합대학 사업단",      kind="www",
         url="https://aicoss.ac.kr/www/notice/", base="https://aicoss.ac.kr"),
    dict(key="nccoss",   name="차세대통신혁신융합대학 사업단",    kind="www",
         url="https://jnu.nccoss.kr/www/notice/", base="https://jnu.nccoss.kr"),
    dict(key="icee",     name="공학교육혁신센터 (ICEE)",         kind="k2web",
         url="https://icee.jnu.ac.kr/bbs/icee/2798/artclList.do"),
    dict(key="diaspora", name="국제이주·디아스포라 BK21",        kind="k2web",
         url="https://diasporabk21.jnu.ac.kr/bbs/diasporabk21/741/artclList.do"),
    dict(key="crdc",     name="지역개발연구소",                 kind="gnuboard",
         url="https://crdcnu.jnuac.kr/bbs/board.php?bo_table=0501"),
    dict(key="coss",     name="첨단분야 혁신융합대학 (COSS)",     kind="linkonly",
         url="https://coss.ac.kr/"),

    # ── 외부 공모전·해커톤 (전공 키워드로 거름, 마감일순) ──────────────
    dict(key="linkareer", name="링커리어 · IT/과학 공모전",       kind="linkareer", group="ext",
         url="https://linkareer.com/list/contest?filterType=CATEGORY&filterBy_categoryIDs=35"),
    dict(key="wevity",   name="위비티 · IT/SW/공학 공모전",        kind="wevity",    group="ext",
         url="https://www.wevity.com/?c=find&s=1&gub=1&cidx=21",
         urls=["https://www.wevity.com/?c=find&s=1&gub=1&cidx=21",    # 게임/소프트웨어
               "https://www.wevity.com/?c=find&s=1&gub=1&cidx=20",    # 웹/모바일/IT
               "https://www.wevity.com/?c=find&s=1&gub=1&cidx=22"]),  # 과학/공학
    dict(key="dacon",    name="데이콘 · AI 경진대회",              kind="dacon",     group="ext",
         url="https://dacon.io/competitions"),
    dict(key="devpost",  name="Devpost · 해외 온라인 해커톤",       kind="devpost",   group="ext",
         url="https://devpost.com/hackathons?status[]=open",
         urls=[f"https://devpost.com/api/hackathons?status[]=open&page={n}" for n in (1, 2, 3)]),
]


# ─────────────────────────────────────────────────────────────
# 공통 유틸
# ─────────────────────────────────────────────────────────────
def _soup(resp):
    if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
        resp.encoding = resp.apparent_encoding
    return BeautifulSoup(resp.text, "lxml")


def _dot_to_iso(s):
    m = re.search(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", s)
    if not m:
        return ""
    y, mo, d = map(int, m.groups())
    try:
        return date(y, mo, d).isoformat()
    except ValueError:
        return ""


def _gnuboard_date(s):
    """그누보드5 목록 날짜: 'HH:MM'(오늘) / 'MM-DD'(올해) / 'YY-MM-DD'(과거)."""
    s = s.strip()
    if re.fullmatch(r"\d{1,2}:\d{2}", s):
        return TODAY.isoformat()
    if re.fullmatch(r"\d{2}-\d{2}-\d{2}", s):
        y, mo, d = int(s[:2]) + 2000, int(s[3:5]), int(s[6:8])
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{1,2}-\d{1,2}", s):
        mo, d = map(int, s.split("-"))
        try:
            dt = date(TODAY.year, mo, d)
        except ValueError:
            return ""
        if dt > TODAY:                    # 미래 날짜면 작년 글 (그누보드 MM-DD 표기)
            try:
                dt = dt.replace(year=TODAY.year - 1)
            except ValueError:
                return ""
        return dt.isoformat()
    return ""


# ─────────────────────────────────────────────────────────────
# 파서: K2Web (ece, icee, diaspora) — table.board-table
# ─────────────────────────────────────────────────────────────
def parse_k2web(resp, src):
    soup = _soup(resp)
    table = soup.select_one("table.board-table")
    if not table:
        return []
    out = []
    for tr in table.select("tr"):
        a = tr.select_one("td.td-subject a, td.td-subject a[href]")
        if not a or not a.get("href"):
            continue
        num = tr.select_one("td.td-num")
        num_txt = num.get_text(strip=True) if num else ""
        dcell = tr.select_one("td.td-date")
        wcell = tr.select_one("td.td-write")
        title = re.sub(r"\s*(새글|new)\s*$", "", a.get_text(" ", strip=True), flags=re.I)
        out.append(dict(
            title=title,
            url=urljoin(src["url"], a["href"]),
            date=_dot_to_iso(dcell.get_text(strip=True)) if dcell else "",
            pinned=not num_txt.isdigit(),
            author=wcell.get_text(strip=True) if wcell else "",
        ))
    return out


# ─────────────────────────────────────────────────────────────
# 파서: 전남대 대표홈 (ASP.NET) — table.board_list
# ─────────────────────────────────────────────────────────────
def parse_jnu(resp, src):
    soup = _soup(resp)
    table = soup.select_one("table.board_list")
    if not table:
        return []
    out = []
    for tr in table.select("tr"):
        a = tr.select_one("td.title a[href]")
        if not a:
            continue
        label = tr.select_one("span.label")
        label_txt = label.get_text(strip=True) if label else ""
        row_txt = tr.get_text(" ", strip=True)
        m = re.search(r"\d{4}-\d{2}-\d{2}", row_txt)
        unders = tr.select("td.under")
        out.append(dict(
            title=a.get_text(" ", strip=True),
            url=urljoin(src["url"], a["href"]),
            date=m.group(0) if m else "",
            pinned=bool(label_txt) and not label_txt.isdigit(),
            author=unders[0].get_text(strip=True) if unders else "",
        ))
    return out


# ─────────────────────────────────────────────────────────────
# 파서: KBoard (sojoong / WordPress)
# ─────────────────────────────────────────────────────────────
def parse_kboard(resp, src):
    soup = _soup(resp)
    out = []
    for td in soup.select("td.kboard-list-title"):
        a = td.select_one('a[href*="mod=document"], a[href*="uid="]')
        if not a or not a.get("href"):
            continue
        tnode = a.select_one("div.kboard-default-cut-strings")
        title = (tnode.get_text(" ", strip=True) if tnode else a.get_text(" ", strip=True))
        title = re.sub(r"^\s*New\s+", "", title).strip()
        tr = td.find_parent("tr")
        cls = tr.get("class") or [] if tr else []
        dm = re.search(r"\d{4}\.\d{2}\.\d{2}", td.get_text(" ", strip=True))
        out.append(dict(
            title=title,
            url=urljoin(src["url"], a["href"].replace("&amp;", "&")),
            date=dm.group(0).replace(".", "-") if dm else "",
            pinned="kboard-list-notice" in cls,
            author="",
        ))
    return out


# ─────────────────────────────────────────────────────────────
# 파서: '/www/' CMS (aicoss, nccoss) — table.basicBoard
# ─────────────────────────────────────────────────────────────
def parse_www(resp, src):
    soup = _soup(resp)
    table = soup.select_one("table.basicBoard")
    if not table:
        return []
    base = src["base"]
    out = []
    for tr in table.select("tr"):
        a = tr.select_one('a[href*="movePageView"]')
        if not a:
            continue
        m = re.search(r"movePageView\((\d+)\)", a["href"])
        if not m:
            continue
        idx = m.group(1)
        strong = a.select_one("strong.cutText")
        title = strong.get_text(" ", strip=True) if strong else a.get_text(" ", strip=True)
        box = tr.select_one("em.boxIcon")
        dm = re.search(r"\d{4}\.\d{2}\.\d{2}", tr.get_text(" ", strip=True))
        out.append(dict(
            title=title,
            url=f"{base}/www/notice/view/{idx}?bd=notice&page=1",
            date=dm.group(0).replace(".", "-") if dm else "",
            pinned=bool(box) and box.get_text(strip=True).lower() == "notice",
            author="",
        ))
    return out


# ─────────────────────────────────────────────────────────────
# 파서: 그누보드5 (crdc)
# ─────────────────────────────────────────────────────────────
def parse_gnuboard(resp, src):
    soup = _soup(resp)
    table = None
    for t in soup.find_all("table"):
        head = t.get_text(" ", strip=True)[:120]
        if "제목" in head and ("날짜" in head or "작성일" in head):
            table = t
            break
    if table is None:
        return []
    out = []
    for tr in table.select("tr"):
        a = tr.select_one('a[href*="wr_id="]')
        if not a:
            continue
        tds = tr.find_all("td")
        num_txt = tds[0].get_text(strip=True) if tds else ""
        d = ""
        for td in tds:
            cand = _gnuboard_date(td.get_text(strip=True))
            if cand:
                d = cand
                break
        href = a["href"].replace(":443", "")
        out.append(dict(
            title=a.get_text(" ", strip=True),
            url=urljoin(src["url"], href),
            date=d,
            pinned="공지" in num_txt,
            author="",
        ))
    return out


# ─────────────────────────────────────────────────────────────
# 외부 공모전 사이트 — 전자컴퓨터공학 전공에 맞는 것만 남기는 필터
# ─────────────────────────────────────────────────────────────
MAJOR_KW = ("ai", "인공지능", "sw", "소프트웨어", "해커톤", "hackathon", "프로그래밍", "코딩",
            "알고리즘", "데이터", "개발", "앱", "웹", "보안", "해킹", "ctf", "사이버", "로봇",
            "로보틱스", "드론", "자율주행", "반도체", "전자", "전기", "회로", "임베디드", "iot",
            "사물인터넷", "클라우드", "블록체인", "메타버스", "통신", "5g", "6g", "ict", "it ",
            "정보", "디지털", "공학", "캡스톤", "모빌리티", "스마트", "llm", "머신러닝", "딥러닝",
            "컴퓨터", "게임 개발", "오픈소스", "챌린지", "challenge", "프로젝트")
EXCLUDE_KW = ("영상", "숏폼", "ucc", "사진", "슬로건", "네이밍", "디카시", "수기", "웹툰", "미디어파사드",
              "광고", " cf", "이벤트", "초·중·고", "초중고", "청소년", "어린이", "초등", "중학생", "고등학생",
              "서포터즈", "기자단", "캐릭터", "노래", "음원", "시나리오", "에세이", "글짓기", "독후감")

def major_match(title, need_kw=True):
    t = " " + title.lower() + " "
    if any(k in t for k in EXCLUDE_KW):
        return False
    return (not need_kw) or any(k in t for k in MAJOR_KW)

def _in_days(n):
    return (TODAY + timedelta(days=n)).isoformat()


# 링커리어 (Next.js) — __NEXT_DATA__ 의 Apollo 캐시에서 Activity 꺼내기
def parse_linkareer(resp, src):
    import json
    from datetime import datetime, timezone
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not m:
        return []
    ap = json.loads(m.group(1))["props"]["pageProps"].get("__APOLLO_STATE__", {})
    kst = timezone(timedelta(hours=9))
    out = []
    for k, v in ap.items():
        if not k.startswith("Activity:") or not v.get("title"):
            continue
        title = v["title"].strip()
        if not major_match(title):
            continue
        dl = ""
        if v.get("recruitCloseAt"):
            dl = datetime.fromtimestamp(v["recruitCloseAt"] / 1000, kst).date().isoformat()
        out.append(dict(title=title, url=f"https://linkareer.com/activity/{v['id']}",
                        date="", pinned=False, author=v.get("organizationName") or "",
                        deadline=dl or None))
    return out


# 위비티 — ul.list > li (분야 여러 개를 한 번에)
def parse_wevity(resp, src):
    soup = _soup(resp)
    out = []
    for li in soup.select("ul.list > li"):
        a = li.select_one("div.tit > a[href]")
        if not a:
            continue
        for sp in a.select("span"):
            sp.decompose()
        title = a.get_text(" ", strip=True)
        day = li.select_one("div.day")
        dtxt = day.get_text(" ", strip=True) if day else ""
        if "마감" in dtxt and "임박" not in dtxt:
            continue
        dm = re.search(r"D-(\d+)", dtxt)
        dl = _in_days(int(dm.group(1))) if dm else (_in_days(0) if "D-day" in dtxt.lower() else None)
        if not major_match(title):
            continue
        ix = re.search(r"ix=(\d+)", a["href"])
        url = (f"https://www.wevity.com/?c=find&s=1&gbn=view&ix={ix.group(1)}"
               if ix else urljoin("https://www.wevity.com/", a["href"]))
        organ = li.select_one("div.organ")
        out.append(dict(title=title, url=url, date="", pinned=False,
                        author=organ.get_text(strip=True) if organ else "", deadline=dl))
    return out


# 데이콘 (Nuxt) — window.__NUXT__ 안의 compData 를 정규식으로
def _nuxt_vars(text):
    """window.__NUXT__=(function(a,b,..){...}(값1,값2,..)) 의 변수 → 값 매핑."""
    import json
    m = re.search(r"window\.__NUXT__=\(function\(([^)]*)\)", text)
    a = re.search(r"\}\((.*)\)\);?\s*</script>", text[m.end():] if m else "", re.S)
    if not m or not a:
        return {}
    try:
        vals = json.loads("[" + a.group(1).replace("void 0", "null") + "]")
    except ValueError:
        return {}
    return dict(zip(m.group(1).split(","), vals))

def parse_dacon(resp, src):
    out = []
    v = _nuxt_vars(resp.text)
    val = lambda tok: tok[1:-1] if tok.startswith('"') else (v.get(tok) or "")
    # 한 대회 객체({...}) 안에서만 매칭되도록 [^{}] 사용
    for m in re.finditer(r'cpt_id:(\d+)[^{}]*?,name:("[^"]*"|\w+)[^{}]*?period_end:("[^"]*"|\w+)',
                         resp.text):
        cid, title, end = m.group(1), val(m.group(2)), str(val(m.group(3)))[:10]
        if not title or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", end) or end < TODAY.isoformat():
            continue
        if not major_match(title, need_kw=False):
            continue
        out.append(dict(title=title, url=f"https://dacon.io/competitions/official/{cid}/overview/description",
                        date="", pinned=False, author="DACON", deadline=end))
    return out


# Devpost — 공개 JSON API (마감 임박순)
_MON = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}

def _devpost_end(s):
    # "Aug 31 - Oct 23, 2026" / "Oct 01 - 23, 2026"
    m = re.search(r"-\s*(?:([A-Z][a-z]{2})\s+)?(\d{1,2}),\s*(\d{4})", s or "")
    if not m:
        return None
    mon = m.group(1) or re.match(r"([A-Z][a-z]{2})", s).group(1)
    try:
        return date(int(m.group(3)), _MON[mon], int(m.group(2))).isoformat()
    except (KeyError, ValueError):
        return None

def parse_devpost(resp, src):
    out = []
    for h in resp.json().get("hackathons", []):
        if h.get("open_state") != "open" or h.get("invite_only"):
            continue
        loc = (h.get("displayed_location") or {}).get("location", "")
        if loc and loc.lower() != "online":       # 오프라인 해외 행사는 제외
            continue
        themes = ", ".join(t["name"] for t in h.get("themes", []))
        out.append(dict(title=h["title"] + (f" — {themes}" if themes else ""),
                        url=h["url"], date="", pinned=False,
                        author=h.get("organization_name") or "",
                        deadline=_devpost_end(h.get("submission_period_dates"))))
    return out


PARSERS = {
    "k2web": parse_k2web,
    "jnu": parse_jnu,
    "kboard": parse_kboard,
    "www": parse_www,
    "gnuboard": parse_gnuboard,
    "linkareer": parse_linkareer,
    "wevity": parse_wevity,
    "dacon": parse_dacon,
    "devpost": parse_devpost,
}
