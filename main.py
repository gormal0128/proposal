import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication # [추가] 엑셀 파일 첨부용
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
    options.add_argument('window-size=1920x1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """NIPA, 기업마당 (제외 단어 삭제)"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    items = []
    
    try:
        res = requests.get(board_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select(css_selector)
        
        for row in rows:
            a_tag = row.select_one('a')
            if not a_tag: continue
                
            title = a_tag.text.strip()
            href = a_tag['href']
            link = base_url + href if href.startswith('/') else href
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            
            if matched_kws:
                try:
                    detail_res = requests.get(link, headers=headers, timeout=10)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    detail_text = detail_soup.get_text(separator=' ') 
                    
                    period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', detail_text)
                    sinchung = period_match.group(1).strip() if period_match else "상세 본문 참조"
                    
                    dates = re.findall(r'\b202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9]\b', detail_text)
                    gongo = dates[0] if dates else "확인필요"
                except:
                    gongo = "로드 실패"
                    sinchung = "로드 실패"

                items.append({
                    "기관": agency_name,
                    "매칭 키워드": ", ".join(matched_kws),
                    "사업명": title,
                    "공고일": gongo,
                    "신청기간": sinchung,
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[상세보기]</a>"
                })
    except Exception as e:
        print(f"[{agency_name}] 에러: {e}")
    return items

def get_nipa(): return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")
def get_bizinfo(): return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")

def get_iris():
    """IRIS 셀레니움 검색 엔진"""
    print("[IRIS] 셀레니움 검색 엔진 가동...")
    items = []
    driver = None
    search_keywords = ['AI', 'ICT', '데이터', '스마트', '수출'] 
    
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        time.sleep(3)
        
        for keyword in search_keywords:
            try:
                search_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "bsnsTl"))
                )
                driver.execute_script("arguments[0].value = '';", search_input)
                search_input.send_keys(keyword)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3) 
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
                
                for row in rows:
                    text_content = row.text.strip()
                    title_tag = row.select_one('a, .tit, strong')
                    if not title_tag: continue
                    
                    title = title_tag.text.strip()
                    
                    js_code = title_tag.get('onclick', '') or title_tag.get('href', '')
                    id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", js_code)
                    
                    if id_match:
                        detail_id = id_match.group(1)
                        link_html = f"<a href='https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={detail_id}' style='color: #0066cc; font-weight: bold;'>[상세보기]</a>"
                    else:
                        link_html = "<a href='https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do' style='color: #0066cc; font-weight: bold;'>[검색화면]</a>"

                    gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', text_content)
                    gongo = gongo_match.group(1).strip() if gongo_match else "상세 확인"
                    
                    if title not in [item['사업명'] for item in items]:
                        items.append({
                            "기관": "IRIS",
                            "매칭 키워드": keyword,
                            "사업명": title,
                            "공고일": gongo,
                            "신청기간": "상세 링크 확인",
                            "링크": link_html
                        })
            except Exception:
                pass 
    except Exception as e:
        print(f"[IRIS] 접속 에러: {e}")
    finally:
        if driver: driver.quit()
    return items


def main():
    print("통합 크롤링 시작...")
    
    # 데이터 수집
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    all_new_data.extend(get_iris()) 
    
    # [핵심] 과거 데이터(히스토리) 불러오기
    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    history_titles = [d.get('사업명', '') for d in history_data]
    
    # 날짜 기준 (아침 9시에 실행되므로, 발견된 시점을 '전일'로 간주하여 수집일 기록)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    target_date_str = yesterday.strftime("%Y-%m-%d")

    daily_new_items = []

    # 신규 공고 찾기
    for item in all_new_data:
        if item['사업명'] not in history_titles:
            # 새로운 공고 발견 시, 수집일 추가 및 히스토리에 병합
            item['수집일'] = target_date_str
            daily_new_items.append(item)
            history_data.append(item)

    # 엑셀 파일 생성 (과거 전체 데이터)
    excel_filename = "ICT_AX_공고_누적히스토리.xlsx"
    if history_data:
        df_history = pd.DataFrame(history_data)
        # 엑셀 출력 시 보기 좋게 열 순서 정리 (상태 칸 삭제됨)
        df_history = df_history[['수집일', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
        # 엑셀은 하이퍼링크 HTML 태그를 제거하고 원본 URL만 남기는 것이 좋습니다
        df_history['링크'] = df_history['링크'].str.extract(r"href='(.*?)'")
        df_history.to_excel(excel_filename, index=False)

    # 이메일 본문 표 생성 (오직 '어제' 발견된 신규 공고만 표시)
    if not daily_new_items:
        daily_new_items.append({
            "기관": "전체", "매칭 키워드": "-",
            "사업명": "전일 기준 신규로 등록된 공고가 없습니다.",
            "공고일": "-", "신청기간": "-", "링크": "-"
        })

    df_daily = pd.DataFrame(daily_new_items)
    # 상태 칸 없이 깔끔하게 구성
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    df_daily = df_daily.sort_values(by=['기관'])

    html_table = df_daily.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    keyword_string = ", ".join(TARGET_KEYWORDS)
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 ICT·AX 신규 사업 공고 (기준일: {target_date_str})
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333;">
            <strong>🎯 대상 기관:</strong> NIPA, 기업마당, IRIS<br>
            <strong>🎯 적용 키워드:</strong> {keyword_string}<br><br>
            <span style="color: #e53935; font-weight: bold;">* 본문에는 전일(어제) 자로 확인된 '신규 공고'만 표시됩니다. 과거 누적 공고는 첨부된 엑셀 파일을 확인해 주세요.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today.strftime('%Y-%m-%d')}] ICT·AX 일일 신규 공고 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    # [핵심] 생성된 엑셀 파일을 이메일에 첨부합니다!
    if os.path.exists(excel_filename):
        with open(excel_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(excel_filename))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(excel_filename)}"'
        msg.attach(part)

    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    # 누적 히스토리 덮어쓰기 (내일 비교를 위해)
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
