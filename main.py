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

# [수정 1] 검색할 대상 기관과 키워드를 상단에 명확히 정의
TARGET_AGENCIES = ["NIPA", "기업마당", "NIA", "IRIS", "KOTRA", "한국전력"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티']

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """기관별 게시판 크롤링 및 키워드 필터링"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
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
            
            # [수정 2] 어떤 키워드에 매칭되었는지 찾아내기
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            
            if matched_kws:
                try:
                    detail_res = requests.get(link, headers=headers, timeout=10)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    content_text = ' '.join(detail_soup.text.split())[:2000] 
                except:
                    content_text = "본문 로드 실패"

                items.append({
                    "기관": agency_name,
                    "사업명": title,
                    "매칭 키워드": ", ".join(matched_kws), # 매칭된 키워드 저장
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>",
                    "본문": content_text
                })
    except Exception as e:
        print(f"[{agency_name}] 크롤링 에러: {e}")
        
    return items

def get_nipa(): return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")
def get_nia(): return fetch_and_filter_board("NIA", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "https://www.nia.or.kr", css_selector='.board_list tbody tr, table tbody tr')
def get_iris(): return fetch_and_filter_board("IRIS", "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do", "https://www.iris.go.kr")
def get_bizinfo(): return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")
def get_kotra(): return fetch_and_filter_board("KOTRA", "https://www.kotra.or.kr/subList/20000020753", "https://www.kotra.or.kr")
def get_kepco(): return fetch_and_filter_board("한국전력", "https://www.kepco.co.kr/eum/program/introduceNotice/boardList.do", "https://www.kepco.co.kr")

def analyze_dates_with_ai(item):
    """[수정 3] AI가 무조건 JSON 형태로만 대답하도록 강제하여 파싱 에러 방지"""
    prompt = f"""
    아래 본문을 읽고 '공고일'과 '신청기간'을 추출해서 반드시 JSON 형식으로만 응답해. 다른 부연설명은 절대 금지.
    제목: {item['사업명']}
    본문: {item['본문']}

    [응답 형식 예시]
    {{"공고일": "2026.04.06", "신청기간": "2026.04.12 ~ 2026.04.23"}}
    (날짜를 찾을 수 없으면 "상세페이지 참조"라고 적어줘)
    """
    
    try:
        response = model.generate_content(prompt)
        # AI가 마크다운(```json)을 붙여도 안전하게 벗겨내는 로직
        res_text = response.text.replace("```json", "").replace("```", "").strip()
        
        # JSON 문자열을 파이썬 딕셔너리로 변환
        date_data = json.loads(res_text)
        
        item['공고일'] = date_data.get('공고일', '확인필요')
        item['신청기간'] = date_data.get('신청기간', '확인필요')
        
    except Exception as e:
        item['공고일'] = "AI 추출 에러"
        item['신청기간'] = "AI 추출 에러"
        
    return item

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
    found_agencies = set() # 공고가 발견된 기관을 기록

    print(f"총 {len(all_new_data)}개 공고 날짜 추출 중...")

    for item in all_new_data:
        found_agencies.add(item['기관'])
        item = analyze_dates_with_ai(item)
        
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)
        time.sleep(2)

    # [수정 4] 검색 결과가 없는 기관 처리
    empty_agencies = set(TARGET_AGENCIES) - found_agencies
    for agency in empty_agencies:
        processed_items.append({
            "상태": "-",
            "기관": agency,
            "매칭 키워드": "-",
            "사업명": "<span style='color: #999;'>조건에 맞는 공고가 없습니다.</span>",
            "공고일": "-",
            "신청기간": "-",
            "링크": "-"
        })

    # 열 순서 지정 및 정렬 (상태 > 기관명 순)
    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    # 결과가 있는 공고가 위로 오도록 정렬
    df['sort_order'] = df['상태'].apply(lambda x: 1 if x in ['🆕 신규', '🔄 진행'] else 2)
    df = df.sort_values(by=['sort_order', '기관'])
    df = df.drop(columns=['sort_order'])

    # HTML 표 생성
    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    # [수정 5] 적용된 전체 키워드 목록 상단 표출
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
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        # 빈 데이터(-)를 저장할 필요는 없으므로 제거 후 저장
        valid_items = [d for d in processed_items if d['상태'] != '-']
        for d in valid_items:
            d.pop('본문', None)
        json.dump(valid_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
