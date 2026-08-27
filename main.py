import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict

# --- 셀레니움 모듈 ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# =========================================================
# ⚙️ 설정
# =========================================================
TEST_MODE = False  # False: 이메일 실제 발송

TARGET_AGENCIES = ["NIPA", "기업마당", "IRIS", "NTIS"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티', 'UAM']

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
BIZINFO_API_KEY = os.getenv("BIZINFO_API_KEY")  # 기업마당 API KEY

LOCAL_REGIONS = ['강원', '경기', '경남', '경북', '광주', '대구', '대전', '부산', '세종', '울산', '인천', '전남', '전북', '제주', '충남', '충북']

# =========================================================
# 🎨 UI 팔레트 (이 아래 값들만 바꾸면 전체 톤이 바뀝니다)
# =========================================================
COLOR_INK = "#12213D"       # 헤드라인 / 기본 텍스트
COLOR_SIGNAL = "#2F6FED"    # 주 액센트 (링크, 섹션 바)
COLOR_SIGNAL_TINT = "#EDF2FE"
COLOR_ALERT = "#FF5A36"     # 키워드 매칭 강조
COLOR_SLATE = "#6D7686"     # 보조 텍스트
COLOR_LINE = "#E3E7EF"      # 구분선/테두리
COLOR_PAPER = "#F4F6FA"     # 배경


def get_chrome_driver():
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-gpu')
    options.add_argument('window-size=1920x1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)


def normalize_date(date_str):
    match = re.search(r'(202[0-9])[-.\/]?([0-1][0-9])[-.\/]?([0-3][0-9])', str(date_str))
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return "확인필요"


# ---------------------------------------------------------
# 1. NIPA
# ---------------------------------------------------------
def get_nipa():
    print("\n[NIPA] 스캔 시작...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    items = []
    try:
        res = requests.get("https://www.nipa.kr/home/2-2", headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        for row in soup.select('tbody tr'):
            a_tag = row.select_one('a')
            if not a_tag:
                continue

            title = a_tag.text.strip()
            if "안내" in title or "결과" in title:
                continue

            row_text = row.text.replace('\n', ' ')
            period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', row_text)
            sinchung = period_match.group(1).strip() if period_match else "상세 확인"

            href = a_tag.get('href', '')
            link = "https://www.nipa.kr" + href if href.startswith('/') else href
            gongo = normalize_date(row_text)

            items.append({
                "기관": "NIPA",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items


# ---------------------------------------------------------
# 2. 기업마당 (API 기반)
# ---------------------------------------------------------
def get_bizinfo():
    print("\n[기업마당] API 스캔 시작...")
    items = []

    api_key = BIZINFO_API_KEY if BIZINFO_API_KEY else "a7bru5"

    try:
        url = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
        params = {
            "crtfcKey": api_key,
            "dataType": "json",
            "searchCnt": "100"
        }

        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()

        data = res.json()
        json_items = data.get('jsonArray', [])

        for item in json_items:
            title = item.get('pblancNm', '')
            if not title:
                continue

            reg_date = item.get('creatPnttm', '')
            gongo = normalize_date(reg_date) if reg_date else "확인필요"

            sinchung = item.get('reqstBeginEndDe', '상세 확인필요')

            link_suffix = item.get('pblancUrl', '')
            if link_suffix.startswith('/'):
                link = "https://www.bizinfo.go.kr" + link_suffix
            else:
                link = link_suffix if link_suffix else "https://www.bizinfo.go.kr"

            items.append({
                "기관": "기업마당",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })

    except Exception as e:
        print(f"[기업마당] API 연동 에러: {e}")

    return items


# ---------------------------------------------------------
# 3. IRIS
# ---------------------------------------------------------
def get_iris():
    print("\n[IRIS] 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '공고일자')]")))
        time.sleep(3)

        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
        for row in rows:
            title_tag = row.select_one('a, .tit')
            if not title_tag:
                continue

            title = title_tag.text.strip()
            if "안내" in title or "결과" in title:
                continue

            ancmDe_span = row.find(class_='ancmDe')
            if ancmDe_span:
                gongo_match = re.search(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', ancmDe_span.text)
            else:
                gongo_match = re.search(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)

            gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"

            a_tag_str = str(title_tag)
            id_match = re.search(r"['\"]([A-Za-z0-9_]{5,15})['\"]", a_tag_str)
            link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmView.do?ancmId={id_match.group(1)}&ancmPrg=ancmIng" if id_match else "상세링크 확인필요"

            sinchung = "상세 접속 필요"
            if title not in [item['사업명'] for item in items]:
                items.append({
                    "기관": "IRIS",
                    "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
                })
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver:
            driver.quit()
    return items


# ---------------------------------------------------------
# 4. NTIS (RSS 파싱)
# ---------------------------------------------------------
def get_ntis_rss():
    print("\n[NTIS] RSS 스캔 시작...")
    items = []
    try:
        url = "http://www.ntis.go.kr/rndgate/unRndRss.xml?prt=100"
        res = requests.get(url, timeout=10)
        res.encoding = 'utf-8'
        root = ET.fromstring(res.text)

        for item in root.findall('.//item'):
            title = item.findtext('title', '').strip()
            link = item.findtext('link', '')
            pubDate = item.findtext('pubDate', '')
            appbegin = item.findtext('appbegin', '')
            appdue = item.findtext('appdue', '')

            gongo = normalize_date(pubDate)
            if appbegin and appdue:
                sinchung = f"{normalize_date(appbegin)} ~ {normalize_date(appdue)}"
            else:
                sinchung = "상세 확인필요"

            items.append({
                "기관": "NTIS",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NTIS] RSS 파싱 에러: {e}")
    return items


# ---------------------------------------------------------
# 지역 분류 함수
# ---------------------------------------------------------
def categorize_region(title):
    match = re.search(r'\[(.*?)\]', title)
    if match:
        region = match.group(1).strip()
        for loc in LOCAL_REGIONS:
            if loc in region:
                return '지방'
    return '전국/서울'


# ---------------------------------------------------------
# 기관별 통계 (오늘 대상 건수 / 키워드 매칭 건수)
# → 웹페이지 상단 "신호 막대" 칩에 쓰임
# ---------------------------------------------------------
def get_agency_stats(items, agencies):
    stats = {a: {"total": 0, "matched": 0} for a in agencies}
    for it in items:
        agency = it.get('기관')
        if agency not in stats:
            continue
        stats[agency]['total'] += 1
        if it.get('매칭 키워드', '-') != '-':
            stats[agency]['matched'] += 1
    return stats


def render_agency_chip(agency, total, matched, max_total):
    scale = max_total if max_total > 0 else 1
    matched_pct = round(matched / scale * 100)
    base_pct = round((total - matched) / scale * 100)
    return f"""      <div class="chip">
        <span class="chip-label">{agency}</span>
        <span class="chip-track">
          <span class="chip-fill chip-fill--match" style="width:{matched_pct}%"></span>
          <span class="chip-fill chip-fill--base" style="width:{base_pct}%"></span>
        </span>
        <span class="chip-count mono">{total}건 · {matched}매칭</span>
      </div>"""


# 웹페이지 전용 CSS (이메일 본문에는 포함되지 않음 → 이메일 클라이언트 호환성 영향 없음)
PAGE_CSS = f"""
    <style>
      :root {{
        --paper: {COLOR_PAPER};
        --ink: {COLOR_INK};
        --signal: {COLOR_SIGNAL};
        --signal-tint: {COLOR_SIGNAL_TINT};
        --alert: {COLOR_ALERT};
        --slate: {COLOR_SLATE};
        --line: {COLOR_LINE};
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        padding: 0;
        background: var(--paper);
        font-family: 'Pretendard', 'Malgun Gothic', sans-serif;
        color: var(--ink);
      }}
      .mono {{ font-family: 'JetBrains Mono', 'Consolas', monospace; }}
      .shell {{ max-width: 1200px; margin: 0 auto; padding: 28px 16px 40px; }}
      .masthead {{
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        flex-wrap: wrap;
        gap: 12px;
        border-bottom: 2px solid var(--ink);
        padding-bottom: 16px;
        margin-bottom: 20px;
      }}
      .masthead-eyebrow {{
        font-size: 12px;
        letter-spacing: 0.18em;
        color: var(--signal);
        font-weight: 700;
        margin: 0 0 6px;
      }}
      .masthead-title {{
        font-size: 26px;
        font-weight: 800;
        margin: 0;
        letter-spacing: -0.02em;
      }}
      .masthead-meta {{
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        color: var(--slate);
      }}
      .live-dot {{
        width: 8px; height: 8px; border-radius: 50%;
        background: var(--alert);
        animation: pulse 2s ease-in-out infinite;
      }}
      @keyframes pulse {{
        0%, 100% {{ opacity: 1; }}
        50% {{ opacity: 0.35; }}
      }}
      @media (prefers-reduced-motion: reduce) {{
        .live-dot {{ animation: none; }}
      }}
      .chip-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-bottom: 8px;
      }}
      .chip {{
        display: flex;
        align-items: center;
        gap: 10px;
        background: #fff;
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 8px 12px;
        flex: 1 1 220px;
      }}
      .chip-label {{
        font-weight: 700;
        font-size: 13px;
        width: 56px;
        flex-shrink: 0;
      }}
      .chip-track {{
        flex: 1;
        display: flex;
        height: 6px;
        border-radius: 3px;
        overflow: hidden;
        background: var(--line);
      }}
      .chip-fill--match {{ background: var(--alert); }}
      .chip-fill--base {{ background: var(--signal); opacity: 0.55; }}
      .chip-count {{
        font-size: 11px;
        color: var(--slate);
        white-space: nowrap;
      }}
      .footer {{
        margin-top: 30px;
        padding-top: 14px;
        border-top: 1px solid var(--line);
        text-align: right;
        color: var(--slate);
        font-size: 12px;
      }}
      table {{ font-family: inherit; }}
      @media (max-width: 640px) {{
        .masthead-title {{ font-size: 20px; }}
        .chip {{ flex: 1 1 100%; }}
      }}
    </style>
"""


# ---------------------------------------------------------
# index.html 생성 함수 (웹페이지 전용 뼈대: 마스트헤드 + 신호칩 + footer)
# 이메일 본문(html_body)은 그대로 감싸서 안에 넣음
# ---------------------------------------------------------
def save_index_html(html_body, agency_stats, today_str):
    # GitHub Actions는 UTC 기준이라 KST(+9시간)로 변환
    now_kst = datetime.datetime.utcnow() + datetime.timedelta(hours=9)
    update_time = now_kst.strftime("%Y-%m-%d %H:%M")

    max_total = max([s['total'] for s in agency_stats.values()] + [1])
    chips_html = "\n".join(
        render_agency_chip(a, agency_stats[a]['total'], agency_stats[a]['matched'], max_total)
        for a in agency_stats
    )

    full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>통합 사업 공고 일일 리포트</title>
    <link rel="preconnect" href="https://cdn.jsdelivr.net">
    <link href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.css" rel="stylesheet">
    <link href="https://cdn.jsdelivr.net/npm/jetbrains-mono@1.0.6/css/jetbrains-mono.css" rel="stylesheet">
{PAGE_CSS}
</head>
<body>
  <div class="shell">
    <div class="masthead">
      <div>
        <p class="masthead-eyebrow mono">DAILY SIGNAL DESK</p>
        <h1 class="masthead-title">통합 사업 공고 일일 리포트</h1>
      </div>
      <div class="masthead-meta mono">
        <span class="live-dot"></span>
        <span>{update_time} KST 갱신</span>
      </div>
    </div>
    <div class="chip-row">
{chips_html}
    </div>
{html_body}
    <div class="footer mono">
        LAST UPDATE {update_time} KST
    </div>
  </div>
</body>
</html>"""

    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(full_html)
    print("✅ 성공! index.html 파일 생성 완료! (UI 리뉴얼 반영)")


def main():
    print(f"\n🚀 통합 크롤링 시작 (TEST_MODE: {TEST_MODE})\n")

    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris())
    all_data.extend(get_ntis_rss())

    for item in all_data:
        matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in item['사업명'].upper()]
        styled_kws = ", ".join(
            [f"<span style='color: {COLOR_ALERT}; font-weight: bold;'>{k}</span>" for k in matched_kws]
        ) if matched_kws else "-"
        item['매칭 키워드'] = styled_kws

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")

    # 💡 최근 3일, 5일 날짜 리스트 각각 생성
    target_dates_3 = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
    target_dates_5 = [(today - datetime.timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]

    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    history_titles = [d.get('사업명', '') for d in history_data]
    for item in all_data:
        if item['사업명'] not in history_titles:
            item['수집일'] = today_str
            history_data.append(item)

    # 히스토리는 넉넉하게 7일 전 데이터까지 유지
    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('수집일', '9999-99-99') >= seven_days_ago_str]

    # 💡 기관별 날짜 필터링 적용 (NIPA, IRIS, NTIS는 5일 / 기업마당은 3일)
    email_items = []
    for item in all_data:
        if item['기관'] in ['NIPA', 'IRIS', 'NTIS']:
            if item['공고일'] in target_dates_5:
                email_items.append(item)
        else:  # 기업마당
            if item['공고일'] in target_dates_3:
                email_items.append(item)

    # 웹페이지 상단 "신호 막대" 칩용 통계 (이메일 본문 계산 전에 원본 email_items 기준으로 산출)
    agency_stats = get_agency_stats(email_items, TARGET_AGENCIES)

    df_daily = pd.DataFrame(email_items)

    if df_daily.empty:
        df_daily = pd.DataFrame([{"기관": "-", "매칭 키워드": "-", "사업명": "해당 조건에 맞는 신규 공고가 없습니다.", "공고일": "-", "신청기간": "-", "링크": "-"}])

    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    df_daily['분류'] = df_daily['사업명'].apply(categorize_region)

    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '공고일', '기관'], ascending=[True, True, False, True])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])

    df_main = df_daily[df_daily['분류'] == '전국/서울'].drop(columns=['분류'])
    df_local = df_daily[df_daily['분류'] == '지방'].drop(columns=['분류'])

    def apply_html_link(df):
        df = df.copy()
        if not df.empty and '링크' in df.columns:
            df['링크'] = df['링크'].apply(
                lambda x: f"<a href='{x}' target='_blank' style='color: {COLOR_SIGNAL}; font-weight: bold;'>[바로가기]</a>" if str(x).startswith('http') else x
            )
        return df

    df_main = apply_html_link(df_main)
    df_local = apply_html_link(df_local)

    def get_table_html(df):
        if df.empty:
            return f"<div style='padding: 20px; text-align: center; color: {COLOR_SLATE}; border: 1px solid {COLOR_LINE}; background-color: #fff; border-radius:8px;'>해당 조건의 공고가 없습니다.</div>"

        html = df.to_html(index=False, escape=False)

        # 💡 테이블 컬럼별 너비(%) 명시적 지정
        table_style = f"""<table style="width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; background-color: #fff;">
        <colgroup>
            <col style="width: 10%;">
            <col style="width: 12%;">
            <col style="width: 48%;">
            <col style="width: 10%;">
            <col style="width: 14%;">
            <col style="width: 6%;">
        </colgroup>"""

        html = html.replace('<table border="1" class="dataframe">', table_style)
        html = html.replace('<th>', f'<th style="background-color: {COLOR_SIGNAL_TINT}; padding: 12px 4px; border: 1px solid {COLOR_LINE}; text-align: center; color:{COLOR_SIGNAL}; font-weight: bold; white-space: nowrap;">')
        html = html.replace('<td>', f'<td style="padding: 10px 6px; border: 1px solid {COLOR_LINE}; text-align: center; word-wrap: break-word; vertical-align: middle;">')

        # 가독성을 위해 '사업명' 데이터만 왼쪽 정렬로 변경
        html = re.sub(
            r'(<tr[^>]*>\s*<td[^>]*>.*?</td>\s*<td[^>]*>.*?</td>\s*)<td([^>]*) style="([^"]*)text-align:\s*center([^"]*)"',
            r'\1<td\2 style="\3text-align: left; padding-left: 15px;\4"', html
        )

        # 모바일 대응: 가로 스크롤 래핑
        return f"<div style='overflow-x:auto; border-radius:8px; border:1px solid {COLOR_LINE};'>{html}</div>"

    html_table_main = get_table_html(df_main)
    html_table_local = get_table_html(df_local)

    html_body = f"""
    <div style="font-family: 'Pretendard','Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: {COLOR_PAPER};">
        <div style="font-size:13px; color:{COLOR_SLATE}; font-weight:700; letter-spacing:0.02em; margin-bottom:6px;">
            기준일 · {today_str}
        </div>
        <div style="background-color: {COLOR_SIGNAL_TINT}; padding: 15px; border-radius: 8px; margin-bottom: 20px; font-size: 13px; color: {COLOR_INK}; line-height: 1.7; border-left: 4px solid {COLOR_SIGNAL};">
            <strong>대상 기관</strong> · {', '.join(TARGET_AGENCIES)}<br>
            <strong>하이라이트 키워드</strong> · {", ".join(TARGET_KEYWORDS)}<br><br>
            <span style="color: {COLOR_SIGNAL}; font-weight: bold;">기업마당은 최근 3일, 그 외 기관(NIPA, IRIS, NTIS)은 최근 5일간 등록된 신규 공고입니다.</span><br>
            <span style="color: {COLOR_ALERT}; font-weight: bold;">키워드 매칭 공고는 표 최상단에 우선 배치됩니다.</span>
        </div>

        <div style="font-size:14px; font-weight:700; margin:24px 0 10px; padding-left:10px; border-left:4px solid {COLOR_SIGNAL};">
            서울 · 전국 단위 공고
        </div>
        {html_table_main}

        <div style="font-size:14px; font-weight:700; margin:32px 0 10px; padding-left:10px; border-left:4px solid {COLOR_SIGNAL};">
            지역별 특화 공고
        </div>
        {html_table_local}
    </div>
    """
    save_index_html(html_body, agency_stats, today_str)

    if TEST_MODE:
        print(df_daily)
        print("\n✅ TEST_MODE 켜짐: 이메일 발송을 생략합니다.")
    else:
        if not RECEIVER_EMAIL or not EMAIL_USER or not EMAIL_PASS:
            print("\n❌ 이메일 환경변수(Secrets)가 누락되어 메일을 보낼 수 없습니다.")
            return

        msg = MIMEMultipart()
        msg['Subject'] = f"[{today_str}] 통합 공고 일일 리포트"
        receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
        msg['To'] = ", ".join(receiver_list)
        msg.attach(MIMEText(html_body, 'html'))

        try:
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
                smtp.login(EMAIL_USER, EMAIL_PASS)
                smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())
            print("\n✅ 성공! 이메일 발송 완료!")
        except Exception as e:
            print(f"\n❌ 이메일 발송 실패: {e}")

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(valid_history, f, ensure_ascii=False, indent=4)
        print("✅ 성공! history.json 파일 업데이트 완료!")


if __name__ == "__main__":
    main()
