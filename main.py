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
from selenium.webdriver.common.keys import Keys

# 환경 변수 설정
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

TARGET_AGENCIES = ["NIPA", "기업마당", "NIA", "IRIS", "KOTRA", "한국전력"]
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
    """일반 크롤링: NIPA, 기업마당, NIA"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
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
        print(f"[{agency_name}] 에러: {e}")
    return items

def get_nipa(): return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")
def get_nia(): return fetch_and_filter_board("NIA", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "https://www.nia.or.kr", css_selector='.board_list tbody tr, table tbody tr')
def get_bizinfo(): return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")

def get_iris():
    """IRIS: 키워드 검색 엔진 (엄격한 공고일자 필터 적용)"""
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
                # JS로 값 완전 초기화 (글자 누적 방지)
                driver.execute_script("arguments[0].value = '';", search_input)
                search_input.send_keys(keyword)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3) 
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                
                # [핵심 필터] 내용 중에 '공고일자'라는 글자가 있는 덩어리만 진짜 공고로 인정!
                rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
                
                for row in rows:
                    text_content = row.text.strip()
                    
                    title_tag = row.select_one('a, .tit, strong')
                    title = title_tag.text.strip() if title_tag else text_content.split('\n')[0][:50]
                    
                    if "안내" in title or "결과" in title: continue
                        
                    gongo_match = re.search(r'공고일자\s*[:|]?\s*(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', text_content)
                    gongo = gongo_match.group(1).strip() if gongo_match else "상세 확인"
                    
                    if title not in [item['사업명'] for item in items]:
                        items.append({
                            "기관": "IRIS",
                            "매칭 키워드": keyword,
                            "사업명": title,
                            "공고일": gongo,
                            "신청기간": "상세 링크 확인",
                            "링크": "<a href='https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do' style='color: #0066cc; font-weight: bold;'>[IRIS 바로가기]</a>"
                        })
            except Exception:
                pass 
    except Exception as e:
        print(f"[IRIS] 접속 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def get_kotra():
    """KOTRA: ID검색 및 엄격한 신청기간 필터 적용"""
    print("[KOTRA] 셀레니움 검색 엔진 가동...")
    items = []
    driver = None
    search_keywords = ['AI', 'ICT', '데이터', '스마트', '수출'] 
    
    try:
        driver = get_chrome_driver()
        driver.get("https://www.kotra.or.kr/subList/20000020753")
        time.sleep(3)
        
        for keyword in search_keywords:
            try:
                # 제보해주신 schwrdVal ID 사용
                search_input = WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "schwrdVal"))
                )
                driver.execute_script("arguments[0].value = '';", search_input)
                search_input.send_keys(keyword)
                search_input.send_keys(Keys.ENTER)
                time.sleep(3)
                
                soup = BeautifulSoup(driver.page_source, 'html.parser')
                
                # [핵심 필터] 내용 중에 '신청기간'이라는 글자가 포함된 블록만 진짜 공고!
                rows = soup.find_all(lambda tag: tag.name in ['li', 'div'] and '신청기간' in tag.text)
                
                for row in rows:
                    text_content = row.text.strip()
                    
                    # 제목 태그 찾기
                    title_tag = row.select_one('strong, .tit, a.title, p.title')
                    title = title_tag.text.strip() if title_tag else text_content.split('\n')[0][:50]
                    
                    if len(title) < 5 or "메뉴" in title: continue
                    
                    period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', text_content)
                    sinchung = period_match.group(1).strip() if period_match else "상세 확인"
                    
                    if title not in [item['사업명'] for item in items]:
                        items.append({
                            "기관": "KOTRA",
                            "매칭 키워드": keyword,
                            "사업명": title,
                            "공고일": "목록 참조",
                            "신청기간": sinchung,
                            "링크": "<a href='https://www.kotra.or.kr/subList/20000020753' style='color: #0066cc; font-weight: bold;'>[KOTRA 바로가기]</a>"
                        })
            except Exception:
                pass
    except Exception as e:
        print(f"[KOTRA] 접속 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def get_kepco():
    return []

def main():
    print("통합 크롤링 시작...")
    
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    all_new_data.extend(get_nia())
    all_new_data.extend(get_iris()) 
    all_new_data.extend(get_kotra())
    all_new_data.extend(get_kepco())
    
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
