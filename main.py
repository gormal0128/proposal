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
TEST_MODE = True # 터미널 출력 모드 (실무 적용 시 False 로 변경)

TARGET_AGENCIES = ["NIPA", "기업마당", "IRIS", "NTIS"]
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
            
            link = "https://www.nipa.kr" + a_tag['href'] if a_tag['href'].startswith('/') else a_tag['href']
            gongo = normalize_date(row_text)
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            items.append({
                "기관": "NIPA", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
            if TEST_MODE: print(f"  👉 [발견] {gongo} | {title[:20]}... | {link}")
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 (링크 추출 완벽 보강)
# ---------------------------------------------------------
def get_bizinfo():
    print("\n[기업마당] 1~5페이지 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        for page in range(1, 6):
            url = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do?rows=15&cpage={page}"
            driver.get(url)
            try: WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
            except: break
                
            time.sleep(1)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            for row in soup.select('tbody tr'):
                tds = row.find_all('td')
                if len(tds) < 7: continue 
                
                title_tag = tds[2].find('a')
                if not title_tag: continue
                
                title = title_tag.text.strip()
                sinchung = tds[3].text.strip()
                gongo = normalize_date(tds[6].text.strip())
                
                # [핵심 보강] 태그 전체 문자열을 뒤져서 PBLN_ 찾기
                a_tag_str = str(title_tag)
                pblancId_match = re.search(r'(PBLN_[A-Za-z0-9_]+)', a_tag_str)
                link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}" if pblancId_match else url

                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                items.append({
                    "기관": "기업마당", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                    "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
                })
            if TEST_MODE: print(f"  👉 {page}페이지 완료 (총 {len(items)}건 누적)")
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 3. IRIS (날짜 추출 보강)
# ---------------------------------------------------------
def get_iris():
    print("\n[IRIS] 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list_area li, tbody tr")))
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.select('.list_area li, tbody tr')
        
        for row in rows:
            title_tag = row.select_one('a, .tit')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            if "안내" in title or "결과" in title: continue
            
            # [핵심 보강] <span> 태그나 전체 텍스트에서 첫 번째 날짜 포맷 추출
            ancmDe_span = row.find(class_='ancmDe')
            if ancmDe_span:
                gongo_match = re.search(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', ancmDe_span.text)
            else:
                gongo_match = re.search(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
                
            gongo = normalize_date(gongo_match.group(1)) if gongo_match else "확인필요"
            
            a_tag_str = str(title_tag)
            id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", a_tag_str)
            link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={id_match.group(1)}" if id_match else "상세링크 확인필요"
                
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            items.append({
                "기관": "IRIS", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": "상세 접속 필요", "링크": link
            })
            if TEST_MODE: print(f"  👉 [발견] {gongo} | {title[:20]}... | {link}")
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 4. NTIS (인덱스 의존 탈피)
# ---------------------------------------------------------
def get_ntis():
    print("\n[NTIS] 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        for row in soup.select('table tbody tr'):
            title_tag = row.select_one('a')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            
            # [핵심 보강] td 인덱스를 믿지 않고 해당 줄에 있는 '모든 날짜'를 다 찾아서 조립
            dates = re.findall(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
            if len(dates) >= 2:
                gongo = normalize_date(dates[0])
                sinchung = f"{normalize_date(dates[0])} ~ {normalize_date(dates[1])}"
            elif len(dates) == 1:
                gongo = normalize_date(dates[0])
                sinchung = "마감일 확인필요"
            else:
                gongo = "확인필요"
                sinchung = "확인필요"
            
            a_tag_str = str(title_tag)
            # goView('12345') 형태의 숫자 ID 추출
            id_match = re.search(r"['\"]([0-9]{4,})['\"]", a_tag_str)
            link = f"https://www.ntis.go.kr/rndgate/eg/un/ra/view.do?pblancNo={id_match.group(1)}" if id_match else "링크 확인필요"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            items.append({
                "기관": "NTIS", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
            if TEST_MODE: print(f"  👉 [발견] {gongo} | {title[:20]}... | {link}")
    except Exception as e:
        print(f"[NTIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

def main():
    print(f"\n🚀 통합 크롤링 시작 (TEST_MODE: {TEST_MODE})\n")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 
    all_data.extend(get_ntis()) 

    # [핵심] 테스트 시 14일 공고가 버려지지 않도록 타겟 날짜를 '최근 3일'로 넓힙니다.
    today = datetime.date.today()
    target_dates = [
        (today).strftime("%Y-%m-%d"),
        (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
        (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d") # 14일 확보용
    ]

    email_items = [item for item in all_data if item['공고일'] in target_dates]

    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency, "매칭 키워드": "-",
                "사업명": "조건에 맞는 최근 공고가 없습니다.",
                "공고일": "-", "신청기간": "-", "링크": "-"
            })

    df_daily = pd.DataFrame(email_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    
    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '공고일', '기관'], ascending=[True, True, False, True])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])

    if TEST_MODE:
        print(f"\n{'='*90}")
        print(f"🎯 [최종 수집 결과] 최근 3일({target_dates[-1]} ~ {target_dates[0]}) 기준")
        print(f"{'='*90}")
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        print(df_daily)
        print(f"{'='*90}")
        print("✅ 성공! 까만 화면 중간의 [발견] 로그와 위 표의 링크를 확인해 보세요.")
        return

if __name__ == "__main__":
    main()
