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
import time # [추가] AI 과부하 방지를 위한 시간 지연 모듈

# 환경 변수 및 AI 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """게시판 긁어오기 공통 함수"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    }
    items = []
    exclude_keywords = ['결과', '안내', '사전규격', '입찰', '취소', '연기', '설명회', '합격']
    
    # [수정] 너무 광범위한 '모집', '지원' 제외, ICT 특화 키워드만 셋팅
    target_keywords = ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증', '데이터', '스마트', '클라우드', '소프트웨어', '바우처']
    
    try:
        res = requests.get(board_url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select(css_selector)
        
        for row in rows:
            a_tag = row.select_one('a')
            if not a_tag: continue
                
            title = a_tag.text.strip()
            href = a_tag['href']
            link = base_url + href if href.startswith('/') else href
            
            if any(ext in title for ext in exclude_keywords): continue
            
            # 타겟 키워드 필터링
            if any(k in title.upper() for k in target_keywords):
                try:
                    detail_res = requests.get(link, headers=headers, timeout=10)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    content_text = ' '.join(detail_soup.text.split())[:1500] 
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

def get_nipa(): return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")
def get_nia(): return fetch_and_filter_board("NIA", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "https://www.nia.or.kr")
def get_iris(): return fetch_and_filter_board("IRIS", "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do", "https://www.iris.go.kr")
def get_bizinfo(): return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")
def get_kotra(): return fetch_and_filter_board("KOTRA", "https://www.kotra.or.kr/subList/20000020753", "https://www.kotra.or.kr")
def get_kepco(): return fetch_and_filter_board("한국전력", "https://www.kepco.co.kr/eum/program/introduceNotice/boardList.do", "https://www.kepco.co.kr")

def analyze_with_ai(item):
    """Gemini를 사용해 추출 (과부하 방지 추가)"""
    prompt = f"""
    아래는 '{item['기관']}'의 사업 공고야. 아래 3가지를 '|' 기호로 구분해서 한 줄로 작성해. 부연설명 절대 금지.
    제목: {item['사업명']}
    본문: {item['본문']}

    1. 신청기간: 본문에서 접수 기간(예: 2026.04.12 ~ 04.23) 추출. (못 찾으면 '상세링크 참조')
    2. 적합성: ICT/AI 기업 관점 참여 적합성 (상/중/하 중 택1)
    3. 아이디어: 참여를 위한 구체적인 액션 아이디어 1문장
    """
    
    try:
        response = model.generate_content(prompt)
        result = response.text.replace('\n', '').strip()
        parts = result.split('|')
        
        if len(parts) >= 3:
            item['신청기간'] = parts[0].strip()
            item['협회 적합성'] = f"<b>{parts[1].strip()}</b>"
            item['제안 아이디어'] = parts[2].strip()
        else:
            raise ValueError("AI가 양식을 지키지 않음")
    except Exception as e:
        item['신청기간'] = "확인필요"
        item['협회 적합성'] = "오류"
        # [수정] 진짜 에러 메시지를 아이디어 칸에 출력하여 원인 파악
        item['제안 아이디어'] = f"에러: {str(e)[:50]}" 
        
    return item

def main():
    print("크롤링 시작...")
    
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    # 우선 2개만 완벽히 동작하는지 테스트하기 위해 임시 주석 처리
    # all_new_data.extend(get_nia())
    # all_new_data.extend(get_iris())
    # all_new_data.extend(get_kotra())
    # all_new_data.extend(get_kepco())
    
    db_file = 'prev_data.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
    else:
        prev_data = []

    processed_items = []
    prev_titles = [d.get('사업명', '') for d in prev_data]

    print(f"총 {len(all_new_data)}개 공고 AI 분석 중...")

    for i, item in enumerate(all_new_data):
        print(f"{i+1}/{len(all_new_data)} 분석 중: {item['사업명'][:15]}...")
        
        item = analyze_with_ai(item)
        
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)
        
        # [핵심] 구글 API 과부하 방지를 위해 1개 분석 후 3초 대기!
        time.sleep(3) 

    if not processed_items:
        print("조건에 맞는 새 공고가 없습니다.")
        return

    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '사업명', '신청기간', '협회 적합성', '제안 아이디어', '링크']]
    df = df.sort_values(by=['기관', '상태'])

    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [통합] ICT·AX 사업 공고 및 AI 인사이트
        </h2>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] 통합 ICT·AX 사업 공고 리포트"
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        for d in processed_items:
            d.pop('본문', None)
        json.dump(processed_items, f, ensure_ascii=False, indent=4)
        
    print("완료!")

if __name__ == "__main__":
    main()
