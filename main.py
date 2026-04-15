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

# =========================================================
# ⚙️ 설정 (테스트 스위치)
# =========================================================
TEST_MODE = True # 터미널 출력 모드 (이메일 안 보냄)

TARGET_AGENCIES = ["NIPA", "기업마당", "IRIS", "NTIS"]
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
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            
            items.append({
                "기관": "NIPA", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당 (href 속성 다이렉트 추출)
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
                
                # [수정] 보내주신 HTML대로 href 주소 100% 그대로 활용!
                href = title_tag.get('href', '')
                if href and not href.startswith('javascript'):
                    link = "https://www.bizinfo.go.kr" + href if href.startswith('/') else href
                else:
                    link = url # 만약의 경우를 위한 검색화면 링크

                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                items.append({
                    "기관": "기업마당", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                    "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
                })
    except Exception as e:
        print(f"[기업마당] 에러: {e}")
    finally:
        if driver: driver.quit()
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
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, ".list_area li, tbody tr")))
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.select('.list_area li, tbody tr')
        
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
            id_match = re.search(r"['\"]([A-Za-z0-9_]{10,})['\"]", a_tag_str)
            link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituDtlView.do?pblancId={id_match.group(1)}" if id_match else "상세링크 확인필요"
                
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            items.append({
                "기관": "IRIS", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": "상세 접속 필요", "링크": link
            })
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 4. NTIS (href 속성 다이렉트 추출)
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
            
            # [수정] 보내주신 HTML대로 href 주소 100% 활용
            href = title_tag.get('href', '')
            if href and not href.startswith('javascript'):
                link = "https://www.ntis.go.kr" + href if href.startswith('/') else href
            else:
                link = "https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            items.append({
                "기관": "NTIS", "매칭 키워드": ", ".join(matched_kws) if matched_kws else "-",
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
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

    today = datetime.date.today()
    # 어제, 그제 공고까지 넉넉히 확인
    target_dates = [
        (today).strftime("%Y-%m-%d"),
        (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d"),
        (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
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
        pd.set_option('display.max_rows', None)
        pd.set_option('display.max_colwidth', None) # 터미널에서 링크가 짤리지 않도록 세팅!
        pd.set_option('display.width', 2000)
        
        print(f"\n{'='*100}")
        print(f"🎯 [최종 수집 결과] 최근 3일({target_dates[-1]} ~ {target_dates[0]}) 기준")
        print(f"{'='*100}")
        print(df_daily)
        print(f"{'='*100}")
        print("✅ 성공! 링크 주소들을 복사해서 인터넷 창에 붙여넣어 보세요!")
        return

    # TEST_MODE = False 일 때 이메일 발송 로직
    html_table = df_daily.copy()
    html_table['링크'] = html_table['링크'].apply(lambda x: f"<a href='{x}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>" if x != '-' else '-')
    
    html_table_str = html_table.to_html(index=False, escape=False)
    html_table_str = html_table_str.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table_str = html_table_str.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table_str = html_table_str.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    for keyword in TARGET_KEYWORDS:
        html_table_str = html_table_str.replace(f'<td>{keyword}</td>', f'<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle; color: #d93025; font-weight: bold;">{keyword}</td>')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 통합 사업 공고 일일 리포트
        </h2>
        {html_table_str}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today.strftime('%Y-%m-%d')}] 통합 공고 일일 리포트"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())
        
    print("✅ 이메일 발송 완료!")

if __name__ == "__main__":
    main()
