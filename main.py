import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
import re
import time

# --- 셀레니움 모듈 ---
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.service import Service

# 환경 변수 설정
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

TARGET_AGENCIES = ["NIPA", "기업마당", "IRIS"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티']

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
    match = re.search(r'(202[0-9])[-.\/]([0-1][0-9])[-.\/]([0-3][0-9])', str(date_str))
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return "확인필요"

def extract_period(text):
    match = re.search(r'([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}\s*(?:~|-)\s*[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', text)
    return match.group(1).strip() if match else "상세 확인"

# ---------------------------------------------------------
# 1. NIPA 수집
# ---------------------------------------------------------
def get_nipa():
    print("[NIPA] 전체 스캔 시작...")
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
            
            link = "https://www.nipa.kr" + a_tag['href'] if a_tag['href'].startswith('/') else a_tag['href']
            gongo = normalize_date(row.text)
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            try:
                detail_res = requests.get(link, headers=headers, timeout=10)
                sinchung = extract_period(BeautifulSoup(detail_res.text, 'html.parser').text)
            except:
                sinchung = "상세 확인"

            items.append({
                "기관": "NIPA", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": sinchung,
                "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 수집 (구조 완벽 대응)
# ---------------------------------------------------------
def get_bizinfo():
    print("[기업마당] 전체 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        # 검색 조작 없이 URL 접속만으로 최신 1페이지를 띄웁니다.
        driver.get("https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do")
        
        # 표(tbody tr)가 로딩될 때까지 기다림
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        for row in soup.select('tbody tr'):
            tds = row.find_all('td')
            if len(tds) < 7: continue # 빈 줄 패스
            
            title_tag = tds[2].find('a')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            # 캡처화면 구조: 4번째 칸(인덱스3)이 신청기간, 7번째 칸(인덱스6)이 등록일(공고일)
            sinchung = tds[3].text.strip()
            gongo = normalize_date(tds[6].text.strip())
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            onclick_attr = title_tag.get('onclick', '')
            pblancId_match = re.search(r"['\"](PBLN_[A-Za-z0-9_]+)['\"]", onclick_attr)
            if pblancId_match:
                raw_link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}"
                link_html = f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            else:
                link_html = "<a href='https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do' style='color: #0066cc; font-weight: bold;'>[검색화면]</a>"

            items.append({
                "기관": "기업마당", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": sinchung, "링크": link_html
            })
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 3. IRIS 수집
# ---------------------------------------------------------
def get_iris():
    print("[IRIS] 전체 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        
        # 검색 없이 1페이지 기본 렌더링 대기
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list_area li, tbody tr")))
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
        
        for row in rows:
            title_tag = row.select_one('a, .tit')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            if "안내" in title or "결과" in title: continue
                
            gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
            gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            js_code = title_tag.get('onclick', '')
            id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", js_code)
            
            if id_match:
                detail_id = id_match.group(1)
                raw_link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={detail_id}"
                link_html = f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            else:
                link_html = "<a href='https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do' style='color: #0066cc; font-weight: bold;'>[검색화면]</a>"
                
            items.append({
                "기관": "IRIS", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": "상세 접속 필요", "링크": link_html
            })
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 메인 실행부
# ---------------------------------------------------------
def main():
    print("통합 무필터 크롤링 시작...")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 

    # --- [핵심] 날짜 기준 설정 ---
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    target_date_str = yesterday.strftime("%Y-%m-%d") # 전일 (어제)

    # 1. 엑셀 생성용 과거 데이터 누적
    db_file = 'history.json'
    history_data = []
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)

    # 중복 없이 히스토리 추가
    history_titles = [d.get('사업명', '') for d in history_data]
    for item in all_data:
        if item['사업명'] not in history_titles:
            history_data.append(item)

    # 최근 1주일 치 데이터만 보관 및 엑셀 저장
    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('공고일', '9999-99-99') >= seven_days_ago_str]

    excel_filename = "ICT_AX_공고_최근1주일.xlsx"
    if valid_history:
        df_history = pd.DataFrame(valid_history)
        df_history = df_history[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
        df_history['링크'] = df_history['링크'].str.extract(r"href='(.*?)'") # HTML 태그 제거
        df_history = df_history.sort_values(by=['공고일', '기관'], ascending=[False, True])
        df_history.to_excel(excel_filename, index=False)

    # 2. 이메일 본문용 데이터 필터링 (무조건 공고일이 '어제'인 것만 추출!)
    email_items = [item for item in all_data if item['공고일'] == target_date_str]

    # 각 기관별로 공고가 있는지 체크하여 빈칸 안내 추가
    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency,
                "매칭 키워드": "-",
                "사업명": f"<span style='color: #999;'>전일({target_date_str}) 기준으로 등록된 공고가 없습니다.</span>",
                "공고일": "-", "신청기간": "-", "링크": "-"
            })

    df_daily = pd.DataFrame(email_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    
    # 정렬: 1순위(키워드 매칭 여부), 2순위(공고 없음 문구 맨 뒤로), 3순위(기관명)
    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '기관'])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])

    # HTML 변환 및 디자인
    html_table = df_daily.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    # 키워드 매칭된 행 글자색 붉은색 강조
    for keyword in TARGET_KEYWORDS:
        html_table = html_table.replace(f'<td>{keyword}</td>', f'<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle; color: #d93025; font-weight: bold;">{keyword}</td>')

    keyword_string = ", ".join(TARGET_KEYWORDS)
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 통합 사업 공고 일일 리포트 (기준일: {target_date_str})
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333; line-height: 1.5;">
            <strong>🎯 대상 기관:</strong> NIPA, 기업마당, IRIS<br>
            <strong>🎯 하이라이트 키워드:</strong> {keyword_string}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 본문에는 분야에 상관없이 어제({target_date_str}) 새롭게 등록된 모든 공고가 나열됩니다.</span><br>
            <span style="color: #e53935; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표의 최상단에 붉은색으로 우선 배치됩니다.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today.strftime('%Y-%m-%d')}] 통합 공고 일일 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    if os.path.exists(excel_filename):
        with open(excel_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(excel_filename))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(excel_filename)}"'
        msg.attach(part)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(valid_history, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
