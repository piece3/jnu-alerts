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


PARSERS = {
    "k2web": parse_k2web,
    "jnu": parse_jnu,
    "kboard": parse_kboard,
    "www": parse_www,
    "gnuboard": parse_gnuboard,
}
