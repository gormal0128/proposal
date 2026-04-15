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

# --- 셀레니움 관련 모듈 ---
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

TARGET_AGENCIES = ["NIPA", "기업마당", "NIA", "IRIS", "KOTRA", "한국전력"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티']

def get_chrome_driver():
    """보이지 않는 크롬 브라우저 세팅"""
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('window-size=1920x1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=options)

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """NIPA, 기업마당, NIA 등 일반적인 사이트 크롤링 (기존 유지)"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    items = []
    exclude_keywords = ['결과', '안내', '사전규격', '입찰', '취소', '연기', '설명회', '합격', '명단']
    
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
            
            if any(ext in title for ext in exclude_keywords): continue
            
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
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
                })
    except Exception as e:
        print(f"[{agency_name}] 크롤링 에러: {e}")
    return items

# --- 일반 크롤링 기관 ---
def get_nipa(): return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")
def get_nia(): return fetch_and_filter_board("NIA", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "https://www.nia.or.kr", css_selector='.board_list tbody tr, table tbody tr')
def get_bizinfo(): return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")

# --- 셀레니움 특수 크롤링 기관 ---

def get_iris():
    """[핵심] IRIS: 검색창에 키워드를 직접 입력하여 검색결과 가져오기"""
    print("[IRIS] 셀레니움으로 키워드 자동 검색을 시작합니다...")
    items = []
    driver = None
    # 11개 키워드를 다 검색하면 너무 오래 걸리므로, 대표 키워드 4개만 압축해서 검색 (필요시 늘리세요)
    search_keywords = ['AI', 'ICT', '데이터', '스마트'] 
    
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        time.sleep(3) # 첫 페이지 로딩 대기
        
        for keyword in search_keywords:
            try:
                # 1. 검색창(input) 찾아서 기존 텍스트 지우고 새 키워드 입력
                search_input = driver.find_element(By.CSS_SELECTOR, "input[title='공고명 입력']") # 캡처본 기준
                search_input.clear()
                search_input.send_keys(keyword)
                
                # 2. 검색 버튼 클릭
                search_btn = driver.find_element(By.CSS_SELECTOR, "button.btn_search, button:contains('검색')")
                driver.execute_script("arguments[0].click();", search_btn)
                time.sleep(3) # 검색 결과가 뜰 때까지 대기
                
                # 3. 검색된 결과 화면 긁어오기
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                # IRIS의 리스트 영역 (보통 클래스명이나 태그로 유추)
                rows = soup.select('.list_area li, tbody tr')
                
                for row in rows:
                    title_tag = row.select_one('.tit, a')
                    if not title_tag: continue
                    title = title_tag.text.strip()
                    
                    if "안내" in title or "결과" in title: continue
                        
                    # 날짜 추출 (화면에 "공고일자 : 2026-04-13" 형태)
                    text_content = row.text
                    gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', text_content)
                    gongo = gongo_match.group(1).strip() if gongo_match else "상세 확인"
                    
                    # 중복 방지를 위해 이미 추가된 사업명인지 체크
                    if title not in [item['사업명'] for item in items]:
                        items.append({
                            "기관": "IRIS",
                            "매칭 키워드": keyword,
                            "사업명": title,
                            "공고일": gongo,
                            "신청기간": "상세 링크 확인", # IRIS는 목록에 신청기간이 잘 안 보임
                            "링크": "<a href='https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do' style='color: #0066cc; font-weight: bold;'>[IRIS 바로가기]</a>"
                        })
            except Exception as inner_e:
                print(f"[IRIS] '{keyword}' 검색 중 에러: {inner_e}")
                continue # 에러 나도 다음 키워드 계속 검색
                
    except Exception as e:
        print(f"[IRIS] 접속 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def get_kotra():
    """KOTRA: 넉넉한 대기시간과 넓은 탐색망으로 데이터 스캔"""
    print("[KOTRA] 셀레니움으로 페이지를 스캔합니다...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.kotra.or.kr/subList/20000020753")
        time.sleep(5) # KOTRA는 자바스크립트가 무거우므로 5초 넉넉히 대기
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        # 사진을 분석해 보면, 하나의 공고가 박스 형태로 되어있음. 최대한 넓게 잡음.
        rows = soup.select('.board-list > li, .list_type1 > li, div.item')
        
        for row in rows:
            text_content = row.text.strip()
            
            # KOTRA 목록 안에서 타겟 키워드 찾기
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in text_content.upper()]
            
            if matched_kws:
                # 제목으로 추정되는 가장 큰 글씨 찾기
                title_tag = row.select_one('strong, .tit, a')
                title = title_tag.text.strip() if title_tag else text_content[:30]+"..."
                
                # 사진에 나와있는 "신청기간 : 2026-04-08 ~ 2026-04-15" 부분 추출
                period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', text_content)
                sinchung = period_match.group(1).strip() if period_match else "상세 확인"
                
                items.append({
                    "기관": "KOTRA",
                    "매칭 키워드": ", ".join(matched_kws),
                    "사업명": title,
                    "공고일": "리스트 참조",
                    "신청기간": sinchung,
                    "링크": "<a href='https://www.kotra.or.kr/subList/20000020753' style='color: #0066cc; font-weight: bold;'>[KOTRA 바로가기]</a>"
                })
    except Exception as e:
        print(f"[KOTRA] 스캔 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def get_kepco(): return [] # 한전은 임시 비활성화 (위 로직이 잘 돌면 추후 추가)

# --- 메인 실행 ---
def main():
    print("통합 크롤링 시작...")
    
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    all_new_data.extend(get_nia())
    all_new_data.extend(get_iris()) # 셀레니움 검색 엔진 가동!
    all_new_data.extend(get_kotra()) # 셀레니움 스캔 엔진 가동!
    
    db_file = 'prev_data.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
    else:
        prev_data = []

    processed_items = []
    prev_titles = [d.get('사업명', '') for d in prev_data]
    found_agencies = set()

    for item in all_new_data:
        found_agencies.add(item['기관'])
        item['상태'] = "🆕 신규" if item['사업명'] not in prev_titles else "🔄 진행"
        processed_items.append(item)

    empty_agencies = set(TARGET_AGENCIES) - found_agencies - {"한국전력"}
    for agency in empty_agencies:
        processed_items.append({
            "상태": "-", "기관": agency, "매칭 키워드": "-",
            "사업명": "<span style='color: #999;'>조건에 맞는 공고가 없습니다.</span>",
            "공고일": "-", "신청기간": "-", "링크": "-"
        })

    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    df['sort_order'] = df['상태'].apply(lambda x: 1 if x in ['🆕 신규', '🔄 진행'] else 2)
    df = df.sort_values(by=['sort_order', '기관'])
    df = df.drop(columns=['sort_order'])

    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    keyword_string = ", ".join(TARGET_KEYWORDS)
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [통합] ICT·AX 사업 공고 일일 리포트
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333;">
            <strong>🎯 현재 적용된 검색 키워드 ({len(TARGET_KEYWORDS)}개):</strong><br>
            {keyword_string}
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] 통합 ICT·AX 공고 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        valid_items = [d for d in processed_items if d['상태'] != '-']
        json.dump(valid_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
