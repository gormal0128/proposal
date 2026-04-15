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
    """어떤 날짜 형식이든 YYYY-MM-DD로 통일하는 헬퍼 함수"""
    match = re.search(r'(202[0-9])[-.\/]([0-1][0-9])[-.\/]([0-3][0-9])', str(date_str))
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return "확인필요"

def extract_period(text):
    """텍스트에서 2026.04.14 ~ 2026.04.28 형태의 기간만 귀신같이 뽑아냅니다"""
    match = re.search(r'([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}\s*(?:~|-)\s*[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', text)
    return match.group(1).strip() if match else "상세 확인"

# ---------------------------------------------------------
# 1. NIPA 수집 (기존 유지)
# ---------------------------------------------------------
def get_nipa():
    print("[NIPA] 스캔 시작...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    items = []
    try:
        res = requests.get("https://www.nipa.kr/home/2-2", headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        for row in soup.select('tbody tr'):
            a_tag = row.select_one('a')
            if not a_tag: continue
            
            title = a_tag.text.strip()
            if not any(k.upper() in title.upper() for k in TARGET_KEYWORDS): continue
            
            link = "https://www.nipa.kr" + a_tag['href'] if a_tag['href'].startswith('/') else a_tag['href']
            
            # 목록에서 공고일(등록일) 추출
            gongo = normalize_date(row.text)
            
            # 상세 페이지에서 신청기간 추출
            try:
                detail_res = requests.get(link, headers=headers, timeout=10)
                sinchung = extract_period(BeautifulSoup(detail_res.text, 'html.parser').text)
            except:
                sinchung = "상세 확인"

            items.append({
                "기관": "NIPA", "사업명": title, "공고일": gongo, "신청기간": sinchung,
                "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 수집 ('내용' 검색 조건 적용)
# ---------------------------------------------------------
def get_bizinfo():
    print("[기업마당] 셀레니움 '내용' 검색 가동...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do")
        time.sleep(3)
        
        # 1) 검색 조건을 '내용'으로 변경
        try:
            dropdown = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button.select_list_open")))
            driver.execute_script("arguments[0].click();", dropdown)
            time.sleep(1)
            content_btn = driver.find_element(By.XPATH, "//button[contains(text(), '내용')]")
            driver.execute_script("arguments[0].click();", content_btn)
        except Exception as e:
            print("[기업마당] 검색 조건 변경 실패 (기본값으로 진행)")

        # 2) 키워드 검색
        search_input = driver.find_element(By.ID, "keyword")
        # 효율을 위해 주요 키워드만 대표로 검색
        for keyword in ['AI', 'ICT', '스마트', '데이터']:
            search_input.clear()
            search_input.send_keys(keyword)
            search_input.send_keys(Keys.ENTER)
            time.sleep(3)
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            for row in soup.select('tbody tr'):
                title_tag = row.select_one('a')
                if not title_tag: continue
                
                title = title_tag.text.strip()
                gongo = normalize_date(row.text) # 목록에 있는 등록일
                
                onclick_attr = title_tag.get('onclick', '')
                pblancId_match = re.search(r"['\"](PBLN_[A-Za-z0-9_]+)['\"]", onclick_attr)
                if pblancId_match:
                    raw_link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}"
                    link_html = f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
                else:
                    raw_link = "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do"
                    link_html = f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[검색화면]</a>"

                if title not in [i['사업명'] for i in items]:
                    items.append({
                        "기관": "기업마당", "사업명": title, "공고일": gongo,
                        "신청기간": "상세 링크 접속 (기업마당 보안)", # 기업마당 상세는 봇 차단이 강해 목록에서 우회
                        "링크": link_html, "raw_link": raw_link
                    })
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
        
    return items

# ---------------------------------------------------------
# 3. IRIS 수집 (상세페이지 진입 & 접수기간 추출)
# ---------------------------------------------------------
def get_iris():
    print("[IRIS] 상세페이지 딥-다이브 검색 가동...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        time.sleep(3)
        
        for keyword in ['AI', 'ICT', '데이터', '스마트']:
            try:
                search_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "bsnsTl")))
                driver.execute_script("arguments[0].value = '';", search_input)
                search_input.send_keys(keyword)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3) 
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
                
                for row in rows:
                    title_tag = row.select_one('a, .tit')
                    if not title_tag: continue
                    title = title_tag.text.strip()
                    
                    gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
                    gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"
                    
                    # 상세 링크 조립
                    js_code = title_tag.get('onclick', '')
                    id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", js_code)
                    
                    if id_match and title not in [i['사업명'] for i in items]:
                        detail_id = id_match.group(1)
                        raw_link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={detail_id}"
                        
                        items.append({
                            "기관": "IRIS", "사업명": title, "공고일": gongo, 
                            "신청기간": "탐색 대기중", 
                            "링크": f"<a href='{raw_link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>",
                            "raw_link": raw_link
                        })
            except Exception:
                pass 
                
        # [핵심] 수집된 IRIS 상세 링크를 하나씩 들어가서 '접수기간'을 정확히 뽑아옵니다.
        print(f"[IRIS] 총 {len(items)}개의 상세페이지 기간 추출 중...")
        for item in items:
            if 'raw_link' in item:
                driver.get(item['raw_link'])
                time.sleep(2) # 상세페이지 로딩 대기
                item['신청기간'] = extract_period(driver.page_source)

    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 메인 실행부 (전일 필터링 & 엑셀 생성)
# ---------------------------------------------------------
def main():
    print("통합 크롤링 시작...")
    
    # 1. 3개 기관 데이터 수집
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 
    
    # 내부 처리용 raw_link 키 삭제
    for item in all_data:
        item.pop('raw_link', None)

    # 2. 날짜 기준 설정
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d") # 전일 (어제)
    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d") # 7일 전

    # 3. 과거 엑셀 데이터 불러오기 (히스토리)
    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    # 신규 수집된 데이터를 히스토리에 병합 (중복 방지)
    history_titles = [d.get('사업명', '') for d in history_data]
    for item in all_data:
        if item['사업명'] not in history_titles:
            history_data.append(item)

    # 4. [엑셀용] 최근 1주일(7일) 치 데이터만 남기고 오래된 것은 삭제
    valid_history = []
    for item in history_data:
        # 공고일이 7일 전보다 크거나 같으면 보관 (또는 날짜 파악이 안 된 것도 일단 보관)
        if item['공고일'] >= seven_days_ago_str or item['공고일'] == '확인필요':
            valid_history.append(item)

    # 엑셀 파일 생성
    excel_filename = "ICT_AX_공고_최근1주일.xlsx"
    if valid_history:
        df_history = pd.DataFrame(valid_history)
        df_history = df_history[['기관', '사업명', '공고일', '신청기간', '링크']]
        # 엑셀은 HTML 태그를 지우고 순수 URL만 남깁니다.
        df_history['링크'] = df_history['링크'].str.extract(r"href='(.*?)'")
        df_history = df_history.sort_values(by=['공고일', '기관'], ascending=[False, True])
        df_history.to_excel(excel_filename, index=False)

    # 5. [이메일 본문용] 오직 '전일(어제)' 날짜로 올라온 공고만 필터링
    daily_items = [item for item in all_data if item['공고일'] == yesterday_str]

    if not daily_items:
        daily_items.append({
            "기관": "전체", "사업명": "전일(어제) 기준으로 새롭게 등록된 공고가 없습니다.",
            "공고일": "-", "신청기간": "-", "링크": "-"
        })

    df_daily = pd.DataFrame(daily_items)
    df_daily = df_daily[['기관', '사업명', '공고일', '신청기간', '링크']]
    df_daily = df_daily.sort_values(by=['기관'])

    # 메일 HTML 디자인
    html_table = df_daily.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 ICT·AX 일일 신규 사업 공고 (기준일: {yesterday_str})
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333;">
            <span style="color: #e53935; font-weight: bold;">* 본문에는 전일(어제) 자로 확인된 신규 공고만 표시됩니다. 최근 1주일 누적 공고는 첨부된 엑셀 파일을 확인해 주세요.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today.strftime('%Y-%m-%d')}] ICT·AX 일일 공고 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    # 엑셀 첨부
    if os.path.exists(excel_filename):
        with open(excel_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(excel_filename))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(excel_filename)}"'
        msg.attach(part)

    # 메일 발송
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    # 1주일 치 데이터 저장 (내일을 위해)
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(valid_history, f, ensure_ascii=False, indent=4)
        
    print("완료! 메일과 엑셀이 성공적으로 발송되었습니다.")

if __name__ == "__main__":
    main()
