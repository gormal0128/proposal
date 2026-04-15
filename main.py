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
from selenium.webdriver.common.keys import Keys

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
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
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
# 1. NIPA 전체 수집
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
            link = "https://www.nipa.kr" + a_tag['href'] if a_tag['href'].startswith('/') else a_tag['href']
            gongo = normalize_date(row.text)
            
            # [변경] 모든 공고에 대해 키워드 포함 여부 검사
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            # 상세 페이지에서 신청기간 추출
            try:
                detail_res = requests.get(link, headers=headers, timeout=10)
                sinchung = extract_period(BeautifulSoup(detail_res.text, 'html.parser').text)
            except:
                sinchung = "상세 확인"

            items.append({
                "기관": "NIPA", 
                "매칭 키워드": kws_str,
                "사업명": title, 
                "공고일": gongo, 
                "신청기간": sinchung,
                "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 전체 수집
# ---------------------------------------------------------
def get_bizinfo():
    print("[기업마당] 전체 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do")
        time.sleep(4) # 리스트 로딩 대기
        
        # [변경] 키워드 검색 반복문 제거. 접속 시 뜨는 전체 공고(기본 리스트)를 바로 긁습니다.
        search_input = driver.find_element(By.ID, "keyword")
        search_input.clear()
        search_input.send_keys(Keys.ENTER) # 빈 검색어로 전체 새로고침
        time.sleep(3)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        for row in soup.select('tbody tr'):
            title_tag = row.select_one('a')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            gongo = normalize_date(row.text)
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            onclick_attr = title_tag.get('onclick', '')
            pblancId_match = re.search(r"['\"](PBLN_[A-Za-z0-9_]+)['\"]", onclick_attr)
            if pblancId_match:
                raw_link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}"
                link_html = f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            else:
                link_html = f"<a href='https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do' style='color: #0066cc; font-weight: bold;'>[검색화면]</a>"

            if title not in [i['사업명'] for i in items]:
                items.append({
                    "기관": "기업마당", 
                    "매칭 키워드": kws_str,
                    "사업명": title, 
                    "공고일": gongo,
                    "신청기간": "상세 링크 접속", 
                    "링크": link_html
                })
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 3. IRIS 전체 수집
# ---------------------------------------------------------
def get_iris():
    print("[IRIS] 전체 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        time.sleep(4)
        
        # [변경] 특정 키워드 검색 제거. 빈 값으로 엔터 쳐서 전체 목록 로딩
        try:
            search_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "bsnsTl")))
            driver.execute_script("arguments[0].value = '';", search_input)
            search_input.send_keys(Keys.ENTER)
            time.sleep(4) 
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
            
            for row in rows:
                title_tag = row.select_one('a, .tit')
                if not title_tag: continue
                title = title_tag.text.strip()
                
                gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
                gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"
                
                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                kws_str = ", ".join(matched_kws) if matched_kws else "-"
                
                js_code = title_tag.get('onclick', '')
                id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", js_code)
                
                if id_match and title not in [i['사업명'] for i in items]:
                    detail_id = id_match.group(1)
                    raw_link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={detail_id}"
                    
                    items.append({
                        "기관": "IRIS", 
                        "매칭 키워드": kws_str,
                        "사업명": title, 
                        "공고일": gongo, 
                        "신청기간": "탐색 대기중", 
                        "링크": f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>",
                        "raw_link": raw_link
                    })
        except Exception as inner_e:
            print(f"[IRIS] 파싱 에러: {inner_e}")
            
        # 수집된 상세 링크 순회하며 접수기간 추출
        print(f"[IRIS] 총 {len(items)}개 전체 공고의 기간을 추출합니다...")
        for item in items:
            if 'raw_link' in item:
                driver.get(item['raw_link'])
                time.sleep(1.5) # 페이지별 짧은 대기
                item['신청기간'] = extract_period(driver.page_source)

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
    
    for item in all_data:
        item.pop('raw_link', None)

    today = datetime.date.today()
    today_str = today.strftime("%Y-%m-%d")

    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    history_titles = [d.get('사업명', '') for d in history_data]
    
    daily_new_items = []
    found_agencies_today = set()

    for item in all_data:
        # DB에 없는 '새로운 공고'만 수집
        if item['사업명'] not in history_titles:
            item['수집일'] = today_str
            daily_new_items.append(item)
            history_data.append(item)
            found_agencies_today.add(item['기관'])

    # 공고가 없는 기관 빈칸 처리
    empty_agencies = set(TARGET_AGENCIES) - found_agencies_today
    for agency in empty_agencies:
        daily_new_items.append({
            "기관": agency,
            "매칭 키워드": "-",
            "사업명": "<span style='color: #999;'>새로 등록된 공고가 없습니다.</span>",
            "공고일": "-",
            "신청기간": "-",
            "링크": "-"
        })

    # 엑셀 파일 생성 (1주일 누적)
    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('수집일', '9999-99-99') >= seven_days_ago_str]

    excel_filename = "ICT_AX_공고_최근1주일.xlsx"
    if valid_history:
        df_history = pd.DataFrame(valid_history)
        df_history = df_history[['수집일', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
        df_history['링크'] = df_history['링크'].str.extract(r"href='(.*?)'")
        df_history.to_excel(excel_filename, index=False)

    # 이메일 본문 표 생성
    df_daily = pd.DataFrame(daily_new_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    
    # [핵심] 정렬 로직: 1순위(키워드 있는 것 위로), 2순위(기관명)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['has_keyword', '기관'])
    df_daily = df_daily.drop(columns=['has_keyword'])

    # 데이터프레임을 HTML 표로 예쁘게 변환
    html_table = df_daily.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    # 키워드가 매칭된 행의 글자색을 파란색으로 돋보이게 하는 약간의 HTML 꼼수
    for keyword in TARGET_KEYWORDS:
        html_table = html_table.replace(f'<td>{keyword}</td>', f'<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle; color: #d93025; font-weight: bold;">{keyword}</td>')

    keyword_string = ", ".join(TARGET_KEYWORDS)
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 전 부처 신규 사업 공고 일일 리포트
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333; line-height: 1.5;">
            <strong>🎯 대상 기관:</strong> NIPA, 기업마당, IRIS<br>
            <strong>🎯 하이라이트 키워드:</strong> {keyword_string}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 본문에는 분야에 상관없이 어제 새롭게 등록된 모든 공고가 나열됩니다.</span><br>
            <span style="color: #e53935; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표의 최상단에 우선 배치됩니다.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today.strftime('%Y-%m-%d')}] 통합 공고 일일 리포트 (키워드 매칭 포함)"
    
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
