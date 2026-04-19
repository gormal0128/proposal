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
BIZINFO_API_KEY = os.getenv("BIZINFO_API_KEY") # 추가된 기업마당 API KEY

LOCAL_REGIONS = ['강원', '경기', '경남', '경북', '광주', '대구', '대전', '부산', '세종', '울산', '인천', '전남', '전북', '제주', '충남', '충북']

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
            if not a_tag: continue
            
            title = a_tag.text.strip()
            if "안내" in title or "결과" in title: continue
            
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
# 2. 기업마당 (자체 API/RSS 기반으로 전면 교체 반영)
# ---------------------------------------------------------
def get_bizinfo():
    print("\n[기업마당] API 스캔 시작...")
    items = []
    
    # 깃허브 시크릿에서 키를 못 가져올 경우 하드코딩된 키(a7bru5) 사용 (테스트용)
    api_key = BIZINFO_API_KEY if BIZINFO_API_KEY else "a7bru5"
    
    try:
        # 매뉴얼 7페이지 기준 요청 URL [cite: 128]
        url = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
        
        # 매뉴얼 6페이지 기준 요청 파라미터 [cite: 118]
        params = {
            "crtfcKey": api_key,
            "dataType": "json",  # 파싱하기 쉽게 JSON 형태로 요청 [cite: 118]
            "searchCnt": "100"   # 최근 100개 데이터 제공 [cite: 118]
        }
        
        # API 호출
        res = requests.get(url, params=params, timeout=15)
        res.raise_for_status()
        
        data = res.json()
        
        # 매뉴얼 14페이지 기준 응답 메시지 구조 (jsonArray 배열 안에 공고 객체들 존재) [cite: 279]
        json_items = data.get('jsonArray', [])
        
        for item in json_items:
            # 사업명 추출 (pblancNm) [cite: 282]
            title = item.get('pblancNm', '')
            if not title: continue
            
            # 등록일자 추출 (creatPnttm) [cite: 284]
            reg_date = item.get('creatPnttm', '')
            gongo = normalize_date(reg_date) if reg_date else "확인필요"
            
            # 신청기간 추출 (reqstBeginEndDe) [cite: 281]
            sinchung = item.get('reqstBeginEndDe', '상세 확인필요')
            
            # 공고 상세 링크 (pblancUrl) [cite: 279]
            # 상대경로(/web/...)로 오는 경우가 있으므로 도메인을 붙여줌
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
            if not title_tag: continue
            
            title = title_tag.text.strip()
            if "안내" in title or "결과" in title: continue
            
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
        if driver: driver.quit()
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

def main():
    print(f"\n🚀 통합 크롤링 시작 (TEST_MODE: {TEST_MODE})\n")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 
    all_data.extend(get_ntis_rss())

    for item in all_data:
        matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in item['사업명'].upper()]
        styled_kws = ", ".join([f"<span style='color: #e83e8c; font-weight: bold;'>{k}</span>" for k in matched_kws]) if matched_kws else "-"
        item['매칭 키워드'] = styled_kws

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    day_before_str = (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    
    target_dates = [today_str, yesterday_str, day_before_str]

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

    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('수집일', '9999-99-99') >= seven_days_ago_str]

    email_items = [item for item in all_data if item['공고일'] in target_dates]
    df_daily = pd.DataFrame(email_items)
    
    if df_daily.empty:
        df_daily = pd.DataFrame([{"기관": "-", "매칭 키워드": "-", "사업명": "최근 3일간 신규 공고가 없습니다.", "공고일": "-", "신청기간": "-", "링크": "-"}])
    
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
            df['링크'] = df['링크'].apply(lambda x: f"<a href='{x}' target='_blank' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>" if str(x).startswith('http') else x)
        return df

    df_main = apply_html_link(df_main)
    df_local = apply_html_link(df_local)

    def get_table_html(df):
        if df.empty:
            return "<div style='padding: 20px; text-align: center; color: #777; border: 1px solid #ddd; background-color: #fff;'>해당 조건의 공고가 없습니다.</div>"
        
        html = df.to_html(index=False, escape=False)
        
        # 💡 테이블 컬럼별 너비(%) 명시적 지정
        table_style = """<table style="width: 100%; border-collapse: collapse; font-size: 13px; table-layout: fixed; background-color: #fff;">
        <colgroup>
            <col style="width: 10%;">  <col style="width: 12%;">  <col style="width: 48%;">  <col style="width: 10%;">  <col style="width: 14%;">  <col style="width: 6%;">   </colgroup>"""
        
        html = html.replace('<table border="1" class="dataframe">', table_style)
        
        # 헤더 스타일 (white-space: nowrap 추가하여 제목 줄바꿈 방지)
        html = html.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px 4px; border: 1px solid #ddd; text-align: center; color:#1a73e8; font-weight: bold; white-space: nowrap;">')
        
        # 데이터 셀 기본 스타일 (모두 가운데 정렬)
        html = html.replace('<td>', '<td style="padding: 10px 6px; border: 1px solid #ddd; text-align: center; word-wrap: break-word; vertical-align: middle;">')
        
        # 💡 가독성을 위해 '사업명' 데이터만 왼쪽 정렬로 변경
        import re
        html = re.sub(r'(<tr[^>]*>\s*<td[^>]*>.*?</td>\s*<td[^>]*>.*?</td>\s*)<td([^>]*) style="([^"]*)text-align:\s*center([^"]*)"', 
                      r'\1<td\2 style="\3text-align: left; padding-left: 15px;\4"', html)
        
        return html

    html_table_main = get_table_html(df_main)
    html_table_local = get_table_html(df_local)

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; background-color: #f9f9f9;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 통합 사업 공고 일일 리포트 [{today_str}]
        </h2>
        <div style="background-color: #f3f6fc; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333; line-height: 1.6; border-left: 4px solid #1a73e8;">
            <strong>🎯 대상 기관:</strong> {', '.join(TARGET_AGENCIES)}<br>
            <strong>🎯 하이라이트 키워드:</strong> {", ".join(TARGET_KEYWORDS)}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 분야에 상관없이 최근 3일간 등록된 신규 공고입니다.</span><br>
            <span style="color: #e83e8c; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표 최상단에 우선 배치됩니다.</span>
        </div>
        
        <h3 style="color: #333; margin-top: 30px; margin-bottom: 10px; padding-left: 5px; border-left: 3px solid #333;">
            📌 서울 / 전국 단위 공고
        </h3>
        {html_table_main}
        
        <h3 style="color: #333; margin-top: 40px; margin-bottom: 10px; padding-left: 5px; border-left: 3px solid #333;">
            📌 지역별 특화 공고
        </h3>
        {html_table_local}
    </div>
    """

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
