import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import google.generativeai as genai
import time

# 환경 변수 및 AI 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """기관별 게시판 크롤링 및 키워드 필터링"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    items = []
    exclude_keywords = ['결과', '안내', '사전규격', '입찰', '취소', '연기', '설명회', '합격', '명단']
    target_keywords = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티']
    
    try:
        res = requests.get(board_url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # [수정] 여러 CSS 선택자를 지원하도록 변경 (NIA 구조 대응)
        rows = soup.select(css_selector)
        
        for row in rows:
            a_tag = row.select_one('a')
            if not a_tag: continue
                
            title = a_tag.text.strip()
            href = a_tag['href']
            link = base_url + href if href.startswith('/') else href
            
            if any(ext in title for ext in exclude_keywords): continue
            
            if any(k.upper() in title.upper() for k in target_keywords):
                try:
                    detail_res = requests.get(link, headers=headers, timeout=10)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    content_text = ' '.join(detail_soup.text.split())[:2000] 
                except:
                    content_text = "본문 로드 실패"

                items.append({
                    "기관": agency_name,
                    "사업명": title,
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>",
                    "본문": content_text
                })
    except Exception as e:
        print(f"[{agency_name}] 크롤링 에러: {e}")
        
    return items

def get_nipa(): return fetch_and_filter_board("NIPA", "[https://www.nipa.kr/home/2-2](https://www.nipa.kr/home/2-2)", "[https://www.nipa.kr](https://www.nipa.kr)")
# [수정] NIA 전용 CSS 구조 추가 (.board_list 또는 일반 테이블 구조)
def get_nia(): return fetch_and_filter_board("NIA", "[https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336](https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336)", "[https://www.nia.or.kr](https://www.nia.or.kr)", css_selector='.board_list tbody tr, table tbody tr')
def get_iris(): return fetch_and_filter_board("IRIS", "[https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do](https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do)", "[https://www.iris.go.kr](https://www.iris.go.kr)")
def get_bizinfo(): return fetch_and_filter_board("기업마당", "[https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do](https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do)", "[https://www.bizinfo.go.kr](https://www.bizinfo.go.kr)")
def get_kotra(): return fetch_and_filter_board("KOTRA", "[https://www.kotra.or.kr/subList/20000020753](https://www.kotra.or.kr/subList/20000020753)", "[https://www.kotra.or.kr](https://www.kotra.or.kr)")
def get_kepco(): return fetch_and_filter_board("한국전력", "[https://www.kepco.co.kr/eum/program/introduceNotice/boardList.do](https://www.kepco.co.kr/eum/program/introduceNotice/boardList.do)", "[https://www.kepco.co.kr](https://www.kepco.co.kr)")

def analyze_dates_with_ai(item):
    """AI 날짜 추출 (에러 추적 강화)"""
    prompt = f"""
    아래 공고 본문에서 '공고일'과 '신청기간'만 찾아줘.
    제목: {item['사업명']}
    본문: {item['본문']}

    [출력형식 규칙]
    1. 반드시 마크다운 기호(```) 쓰지 마.
    2. 다른 부연설명 절대 하지 마.
    3. 딱 아래 형식처럼 '|' 기호로만 구분해서 한 줄로 대답해.
    공고일|신청기간
    """
    
    try:
        response = model.generate_content(prompt)
        # 불필요한 마크다운이나 공백 강제 제거
        result = response.text.replace('\n', '').replace('```', '').replace('markdown', '').strip()
        parts = result.split('|')
        
        if len(parts) >= 2:
            item['공고일'] = parts[0].strip()
            item['신청기간'] = parts[1].strip()
        else:
            item['공고일'] = "형식오류"
            # AI가 대체 뭐라고 대답했는지 확인하기 위해 신청기간 칸에 원문 출력
            item['신청기간'] = result[:30] 
    except Exception as e:
        item['공고일'] = "AI에러"
        item['신청기간'] = str(e)[:30]
        
    return item

def main():
    print("통합 크롤링 시작...")
    
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    all_new_data.extend(get_nia())
    # 자바스크립트 렌더링 사이트들은 현재 빈 리스트를 반환할 확률이 높습니다.
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

    for i, item in enumerate(all_new_data):
        item = analyze_dates_with_ai(item)
        
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)
        time.sleep(2) 

    if not processed_items:
        print("조건에 맞는 공고가 없습니다.")
        return

    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '사업명', '공고일', '신청기간', '링크']]
    df = df.sort_values(by=['상태', '기관'], ascending=[False, True])

    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [통합] ICT·AX 사업 공고 일일 리포트
        </h2>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] 통합 ICT·AX 공고 리포트"
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        for d in processed_items:
            d.pop('본문', None)
        json.dump(processed_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
