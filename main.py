import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
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

# 1. NIPA
def get_nipa():
    print("[NIPA] 1페이지 스캔...")
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
            
            items.append({
                "기관": "NIPA", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": "상세 접속 필요", "링크": link
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# 2. 기업마당 (1~5페이지 싹쓸이 적용)
def get_bizinfo():
    print("[기업마당] 1~5페이지 집중 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        
        # [핵심] 작성자님이 알려주신 페이징 로직 적용 (1페이지부터 5페이지까지)
        for page in range(1, 6):
            url = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do?rows=15&cpage={page}"
            driver.get(url)
            
            try:
                # 표가 로딩될 때까지 최대 10초 대기
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
            except:
                print(f"[기업마당] {page}페이지 로딩 실패 또는 데이터 없음")
                break
                
            time.sleep(1) # 렌더링 안정화
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            for row in soup.select('tbody tr'):
                tds = row.find_all('td')
                if len(tds) < 7: continue 
                
                title_tag = tds[2].find('a')
                if not title_tag: continue
                
                title = title_tag.text.strip()
                sinchung = tds[3].text.strip()
                gongo = normalize_date(tds[6].text.strip())
                
                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                kws_str = ", ".join(matched_kws) if matched_kws else "-"
                
                onclick_attr = title_tag.get('onclick', '')
                pblancId_match = re.search(r"['\"](PBLN_[A-Za-z0-9_]+)['\"]", onclick_attr)
                
                link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}" if pblancId_match else url

                items.append({
                    "기관": "기업마당", "매칭 키워드": kws_str, "사업명": title, 
                    "공고일": gongo, "신청기간": sinchung, "링크": link
                })
            print(f" -> 기업마당 {page}페이지 수집 완료")
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# 3. IRIS (특수기호 에러 해결)
def get_iris():
    print("[IRIS] 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list_area li, tbody tr")))
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
        
        for row in rows:
            title_tag = row.select_one('a, .tit')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            if "안내" in title or "결과" in title: continue
            
            # [핵심] '공고일자 : | 2026-04-14' 같은 기괴한 형태도 뚫어버리는 무적의 정규표현식
            gongo_match = re.search(r'공고일자.*?([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', row.text)
            gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            js_code = title_tag.get('onclick', '')
            id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", js_code)
            
            link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={id_match.group(1)}" if id_match else "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do"
                
            items.append({
                "기관": "IRIS", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": "상세 접속 필요", "링크": link
            })
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def main():
    print("통합 무필터 크롤링 시작 (빠른 테스트 모드)...")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 

    # [핵심] 날짜 타겟팅: '오늘'과 '어제' 두 날짜를 모두 허용 리스트에 넣습니다.
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    target_dates = [today_str, yesterday_str]

    # 오늘 or 어제 날짜인 공고만 쏙쏙 뽑아냅니다.
    email_items = [item for item in all_data if item['공고일'] in target_dates]

    # 빈칸 채우기
    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency,
                "매칭 키워드": "-",
                "사업명": f"어제({yesterday_str}) 및 오늘({today_str}) 기준 등록된 공고가 없습니다.",
                "공고일": "-", "신청기간": "-", "링크": "-"
            })

    print(f"\n{'='*90}")
    print(f"🚀 [테스트 결과] {yesterday_str} ~ {today_str} 기준 공고 (총 {len([i for i in email_items if i['공고일'] != '-'])}건)")
    print(f"{'='*90}")

    # 보기 좋게 터미널 출력
    pd.set_option('display.max_rows', None)
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)
    
    df_daily = pd.DataFrame(email_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간']]
    
    # 정렬 (키워드 매칭된 것 최상단)
    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '공고일', '기관'], ascending=[True, True, False, True])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])
    
    print(df_daily)
    print(f"{'='*90}")
    print("테스트가 무사히 종료되었습니다.")

if __name__ == "__main__":
    main()
