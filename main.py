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
TEST_MODE = False # 실무 발송 모드 (이메일 발송)

TARGET_AGENCIES = ["NIPA", "기업마당", "IRIS", "NTIS"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티', 'UAM']

EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

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
            
            styled_kws = ", ".join([f"<span style='color: #e83e8c; font-weight: bold;'>{k}</span>" for k in matched_kws]) if matched_kws else "-"
            
            items.append({
                "기관": "NIPA", "매칭 키워드": styled_kws,
                "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
            })
    except Exception as e:
        print(f"[NIPA] 에러: {e}")
    return items

# ---------------------------------------------------------
# 2. 기업마당
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
                
                href = title_tag.get('href', '')
                if href and not href.startswith('javascript'):
                    link = "https://www.bizinfo.go.kr" + href if href.startswith('/') else href
                else:
                    link = url

                matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
                styled_kws = ", ".join([f"<span style='color: #e83e8c; font-weight: bold;'>{k}</span>" for k in matched_kws]) if matched_kws else "-"
                
                items.append({
                    "기관": "기업마당", "매칭 키워드": styled_kws,
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
        
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.XPATH, "//*[contains(text(), '공고일자')]")))
        time.sleep(3) 
        
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        rows = soup.find_all(lambda tag: tag.name in ['li', 'tr'] and '공고일자' in tag.text)
        
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
            id_match = re.search(r"['\"]([A-Za-z0-9_]{5,15})['\"]", a_tag_str)
            
            link = f"https://www.iris.go.kr/contents/retrieveBsnsAncmView.do?ancmId={id_match.group(1)}&ancmPrg=ancmIng" if id_match else "상세링크 확인필요"
            
            sinchung = "상세 접속 필요"
            if id_match:
                try:
                    det_res = requests.get(link, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                    det_soup = BeautifulSoup(det_res.text, 'html.parser')
                    det_text = det_soup.get_text(separator=' ')
                    
                    period_match = re.search(r'접수기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', det_text)
                    if period_match:
                        sinchung = period_match.group(1).strip()
                except:
                    sinchung = "상세 접속 필요"
                
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            styled_kws = ", ".join([f"<span style='color: #e83e8c; font-weight: bold;'>{k}</span>" for k in matched_kws]) if matched_kws else "-"
            
            if title not in [item['사업명'] for item in items]:
                items.append({
                    "기관": "IRIS", "매칭 키워드": styled_kws,
                    "사업명": title, "공고일": gongo, "신청기간": sinchung, "링크": link
                })
    except Exception as e:
        print(f"[IRIS] 에러: {e}")
    finally:
        if driver: driver.quit()
    return items

# ---------------------------------------------------------
# 4. NTIS
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
            
            href = title_tag.get('href', '')
            if href and not href.startswith('javascript'):
                link = "https://www.ntis.go.kr" + href if href.startswith('/') else href
            else:
                link = "https://www.ntis.go.kr/rndgate/eg/un/ra/mng.do"
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            styled_kws = ", ".join([f"<span style='color: #e83e8c; font-weight: bold;'>{k}</span>" for k in matched_kws]) if matched_kws else "-"
            
            items.append({
                "기관": "NTIS", "매칭 키워드": styled_kws,
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
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = (today - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    day_before_str = (today - datetime.timedelta(days=2)).strftime("%Y-%m-%d")
    
    target_dates = [today_str, yesterday_str, day_before_str]

    # =========================================================
    # 히스토리 누적 로직 (새 공고 판별용으로만 사용)
    # =========================================================
    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    history_titles = [d.get('사업명', '') for d in history_data]
    for item in all_data:
        if item['사업명'] not in history_titles:
            item['수집일'] = today_str
            history_data.append(item)

    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('수집일', '9999-99-99') >= seven_days_ago_str]

    # =========================================================
    # 이메일 본문 생성 로직
    # =========================================================
    email_items = [item for item in all_data if item['공고일'] in target_dates]

    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency, "매칭 키워드": "-",
                "사업명": f"조건에 맞는 최근({target_dates[-1]}~{target_dates[0]}) 공고가 없습니다.",
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
        pd.set_option('display.max_colwidth', None)
        pd.set_option('display.width', 2000)
        print(df_daily)
        print("✅ 터미널 테스트 완료 (이메일 발송 생략)")
        return

    html_table = df_daily.copy()
    html_table['링크'] = html_table['링크'].apply(lambda x: f"<a href='{x}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>" if x != '-' else '-')
    
    html_table_str = html_table.to_html(index=False, escape=False)
    html_table_str = html_table_str.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table_str = html_table_str.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table_str = html_table_str.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 통합 사업 공고 일일 리포트
        </h2>
        <div style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 20px; font-size: 13px; color: #333; line-height: 1.5;">
            <strong>🎯 대상 기관:</strong> {', '.join(TARGET_AGENCIES)}<br>
            <strong>🎯 하이라이트 키워드:</strong> {", ".join(TARGET_KEYWORDS)}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 본문에는 분야에 상관없이 최근 3일간 등록된 모든 공고가 나열됩니다.</span><br>
            <span style="color: #e83e8c; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표의 최상단에 우선 배치됩니다.</span>
        </div>
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
        
    print("\n✅ 성공! 이메일 발송 완료!")

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(valid_history, f, ensure_ascii=False, indent=4)
        print("✅ 성공! history.json 파일 업데이트 완료!")

if __name__ == "__main__":
    main()
