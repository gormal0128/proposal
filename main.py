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

# =========================================================
# ⚙️ 설정 (테스트 모드 스위치)
# =========================================================
# True로 두면 이메일을 보내지 않고 터미널에 즉시 결과를 출력합니다.
# 실무에 적용하실 때는 False 로 변경해 주세요!
TEST_MODE = True 

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

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
# 1. NIPA 수집 (리스트 텍스트 직접 추출)
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
            if "안내" in title or "결과" in title: continue
            
            # [수정] 상세 접속 없이 화면에 표출된 "신청기간 : 0000-00-00 ~ 0000-00-00" 바로 추출
            row_text = row.text.replace('\n', ' ')
            period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}(?:\s*[0-9]{2}:[0-9]{2})?)', row_text)
            sinchung = period_match.group(1).strip() if period_match else "상세 확인"
            
            link = "https://www.nipa.kr" + a_tag['href'] if a_tag['href'].startswith('/') else a_tag['href']
            gongo = normalize_date(row_text)
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            items.append({
                "기관": "NIPA", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 수집 (고유 링크 PBLN 추출 완벽 대응)
# ---------------------------------------------------------
def get_bizinfo():
    print("[기업마당] 1~5페이지 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        for page in range(1, 6):
            url = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do?rows=15&cpage={page}"
            driver.get(url)
            
            try:
                WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "tbody tr")))
            except:
                break
                
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
                
                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                kws_str = ", ".join(matched_kws) if matched_kws else "-"
                
                # [수정] PBLN_ 으로 시작하는 고유 아이디를 추출하여 다이렉트 링크 조립
                onclick_attr = title_tag.get('onclick', '')
                pblancId_match = re.search(r"(PBLN_[A-Za-z0-9_]+)", onclick_attr)
                link = f"https://www.bizinfo.go.kr/sii/siia/selectSIIA200Detail.do?pblancId={pblancId_match.group(1)}" if pblancId_match else url

                items.append({
                    "기관": "기업마당", "매칭 키워드": kws_str, "사업명": title, 
                    "공고일": gongo, "신청기간": sinchung, "링크": link
                })
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 3. IRIS 수집 (<span class="ancmDe"> 강제 타겟팅)
# ---------------------------------------------------------
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
            
            # [수정] 캡처 화면의 'ancmDe' 클래스를 정확하게 조준하여 날짜 추출
            ancmDe_span = row.find('span', class_='ancmDe')
            if ancmDe_span:
                gongo = normalize_date(ancmDe_span.text)
            else:
                gongo_match = re.search(r'(202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9])', row.text)
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

# ---------------------------------------------------------
# 4. NTIS (국가과학기술지식정보서비스) 신규 수집
# ---------------------------------------------------------
def get_ntis():
    print("[NTIS] 스캔 시작...")
    items = []
    driver = None
    try:
        driver = get_chrome_driver()
        driver.get("https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do")
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "table tbody tr")))
        time.sleep(2)
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        
        for row in soup.select('table tbody tr'):
            tds = row.find_all('td')
            if len(tds) < 7: continue
            
            title_tag = tds[3].find('a')
            if not title_tag: continue
            
            title = title_tag.text.strip()
            
            # NTIS는 5번째 열이 접수일(공고일), 6번째 열이 마감일
            gongo = normalize_date(tds[5].text.strip())
            magam = normalize_date(tds[6].text.strip())
            sinchung = f"{gongo} ~ {magam}"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            kws_str = ", ".join(matched_kws) if matched_kws else "-"
            
            # NTIS 고유 링크 조립
            onclick_attr = title_tag.get('onclick', '')
            id_match = re.search(r"['\"]([a-zA-Z0-9_-]+)['\"]", onclick_attr)
            link = f"https://www.ntis.go.kr/rndgate/eg/un/ra/view.do?pblancNo={id_match.group(1)}" if id_match else "https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do"
            
            items.append({
                "기관": "NTIS", "매칭 키워드": kws_str, "사업명": title, 
                "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NTIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 메인 실행부
# ---------------------------------------------------------
def main():
    print(f"통합 무필터 크롤링 시작 (TEST_MODE: {TEST_MODE})...")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 
    all_data.extend(get_ntis()) # NTIS 가동

    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    # [핵심] 어제와 오늘 등록된 공고를 모두 수집합니다.
    target_dates = [today_str, yesterday_str]

    email_items = []
    for item in all_data:
        if item['공고일'] in target_dates:
            # HTML 하이퍼링크 입히기 (테스트 모드가 아닐 때만)
            if not TEST_MODE:
                item['링크'] = f"<a href='{item['링크']}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            email_items.append(item)

    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency, "매칭 키워드": "-",
                "사업명": f"<span style='color: #999;'>어제({yesterday_str}) 및 오늘({today_str}) 기준 공고가 없습니다.</span>" if not TEST_MODE else "조건에 맞는 공고가 없습니다.",
                "공고일": "-", "신청기간": "-", "링크": "-"
            })

    # 정렬: 키워드 유무 > 빈칸 맨아래 > 공고일 최신순 > 기관명
    df_daily = pd.DataFrame(email_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    
    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '공고일', '기관'], ascending=[True, True, False, True])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])

    # =========================================================
    # 결과 처리 분기 (TEST_MODE 유무)
    # =========================================================
    if TEST_MODE:
        print(f"\n{'='*90}")
        print(f"🚀 [테스트 결과] {yesterday_str} ~ {today_str} 기준 신규 수집 공고")
        print(f"{'='*90}")
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_columns', None)
        pd.set_option('display.width', 1000)
        print(df_daily)
        print(f"{'='*90}")
        print("✅ 테스트 모드가 무사히 종료되었습니다. (이메일 발송은 생략됨)")
        print("만족스러우시다면 코드 상단의 TEST_MODE = False 로 변경하세요.")
        return # 테스트 모드면 여기서 스크립트를 즉시 종료합니다.

    # --- 여기서부터는 이메일 발송 모드 (TEST_MODE = False 일 때만 실행됨) ---
    
    html_table = df_daily.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    for keyword in TARGET_KEYWORDS:
        html_table = html_table.replace(f'<td>{keyword}</td>', f'<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle; color: #d93025; font-weight: bold;">{keyword}</td>')

    keyword_string = ", ".join(TARGET_KEYWORDS)
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 통합 사업 공고 일일 리포트
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333; line-height: 1.5;">
            <strong>🎯 대상 기관:</strong> {', '.join(TARGET_AGENCIES)}<br>
            <strong>🎯 하이라이트 키워드:</strong> {keyword_string}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 본문에는 분야에 상관없이 어제({yesterday_str})와 오늘({today_str}) 등록된 모든 공고가 나열됩니다.</span><br>
            <span style="color: #e53935; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표의 최상단에 붉은색으로 우선 배치됩니다.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today_str}] 통합 공고 일일 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    # 이메일 발송
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())
        
    print("✅ 성공! 이메일이 발송되었습니다.")

if __name__ == "__main__":
    main()
