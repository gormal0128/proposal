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

# 1. NIPA 수집
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

# 2. 기업마당 수집 (1~5페이지 싹쓸이)
def get_bizinfo():
    print("[기업마당] 1~5페이지 집중 스캔 시작...")
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
                
                onclick_attr = title_tag.get('onclick', '')
                pblancId_match = re.search(r"['\"](PBLN_[A-Za-z0-9_]+)['\"]", onclick_attr)
                
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

# 3. IRIS 수집 (특수기호 완벽 대응)
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
    print("통합 무필터 크롤링 시작 (이메일 발송 모드)...")
    
    all_data = []
    all_data.extend(get_nipa())
    all_data.extend(get_bizinfo())
    all_data.extend(get_iris()) 

    # [핵심] 기준 날짜 (어제와 오늘 모두 잡기)
    today = datetime.date.today()
    yesterday = today - datetime.timedelta(days=1)
    
    today_str = today.strftime("%Y-%m-%d")
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    target_dates = [today_str, yesterday_str]

    # --- 엑셀 생성을 위한 히스토리 누적 ---
    db_file = 'history.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            history_data = json.load(f)
    else:
        history_data = []

    # 새로 찾은 공고를 히스토리에 추가
    history_titles = [d.get('사업명', '') for d in history_data]
    for item in all_data:
        if item['사업명'] not in history_titles:
            item['수집일'] = today_str
            history_data.append(item)

    # 최근 7일 치 히스토리만 엑셀로 저장
    seven_days_ago_str = (today - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    valid_history = [item for item in history_data if item.get('수집일', '9999-99-99') >= seven_days_ago_str]

    excel_filename = "ICT_AX_공고_최근1주일.xlsx"
    if valid_history:
        df_history = pd.DataFrame(valid_history)
        df_history = df_history[['수집일', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
        df_history = df_history.sort_values(by=['수집일', '기관'], ascending=[False, True])
        df_history.to_excel(excel_filename, index=False)

    # --- 이메일 본문 표 만들기 (어제, 오늘 공고만) ---
    email_items = []
    for item in all_data:
        if item['공고일'] in target_dates:
            # 하이퍼링크 HTML 씌우기
            item['링크'] = f"<a href='{item['링크']}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
            email_items.append(item)

    # 공고가 없는 기관 빈칸 추가
    found_agencies = set([item['기관'] for item in email_items])
    for agency in TARGET_AGENCIES:
        if agency not in found_agencies:
            email_items.append({
                "기관": agency,
                "매칭 키워드": "-",
                "사업명": f"<span style='color: #999;'>어제({yesterday_str}) 및 오늘({today_str}) 기준 등록된 공고가 없습니다.</span>",
                "공고일": "-", "신청기간": "-", "링크": "-"
            })

    # 정렬 및 표 생성
    df_daily = pd.DataFrame(email_items)
    df_daily = df_daily[['기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    
    df_daily['is_empty'] = df_daily['공고일'].apply(lambda x: 1 if x == '-' else 0)
    df_daily['has_keyword'] = df_daily['매칭 키워드'].apply(lambda x: 1 if x == '-' else 0)
    df_daily = df_daily.sort_values(by=['is_empty', 'has_keyword', '공고일', '기관'], ascending=[True, True, False, True])
    df_daily = df_daily.drop(columns=['is_empty', 'has_keyword'])

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
            <strong>🎯 대상 기관:</strong> NIPA, 기업마당, IRIS<br>
            <strong>🎯 하이라이트 키워드:</strong> {keyword_string}<br><br>
            <span style="color: #1a73e8; font-weight: bold;">* 본문에는 분야에 상관없이 어제({yesterday_str})와 오늘({today_str}) 등록된 모든 공고가 나열됩니다.</span><br>
            <span style="color: #e53935; font-weight: bold;">* 타겟 키워드가 매칭된 공고는 표의 최상단에 붉은색으로 우선 배치됩니다.</span>
        </div>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{today_str}] 통합 공고 일일 리포트 (엑셀 첨부)"
    
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    # 엑셀 파일 메일에 첨부
    if os.path.exists(excel_filename):
        with open(excel_filename, 'rb') as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(excel_filename))
        part['Content-Disposition'] = f'attachment; filename="{os.path.basename(excel_filename)}"'
        msg.attach(part)

    # 이메일 발송!
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    # 누적 데이터 갱신
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(valid_history, f, ensure_ascii=False, indent=4)
        
    print("✅ 성공! 이메일이 발송되었습니다.")

if __name__ == "__main__":
    main()
