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

# 환경 변수 및 AI 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# ---------------------------------------------------------
# [크롤링 함수 모음] 각 기관별로 함수를 분리하여 관리합니다.
# ---------------------------------------------------------

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """게시판을 긁어오고 키워드 필터링을 하는 공통 헬퍼 함수"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    items = []
    exclude_keywords = ['결과', '안내', '사전규격', '입찰', '취소', '연기', '설명회', '합격']
    target_keywords = ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증', '모집', '지원', '데이터', '스마트']
    
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
            
            # 1차 필터링: 쓸데없는 공고 제외
            if any(ext in title for ext in exclude_keywords): continue
            
            # 2차 필터링: 타겟 키워드가 있는 공고만 수집
            if any(k in title for k in target_keywords):
                # 상세페이지 본문 긁어오기
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

def get_nipa():
    return fetch_and_filter_board("NIPA", "https://www.nipa.kr/home/2-2", "https://www.nipa.kr")

def get_nia():
    # NIA 게시판 URL
    return fetch_and_filter_board("NIA", "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336", "https://www.nia.or.kr")

def get_iris():
    # IRIS는 JS/AJAX를 많이 쓰지만 기본 HTML 표가 있는지 우선 테스트
    return fetch_and_filter_board("IRIS", "https://www.iris.go.kr/contents/retrieveBsnsAncmBtinSituListView.do", "https://www.iris.go.kr")

def get_bizinfo():
    # 기업마당 지원사업 공고
    return fetch_and_filter_board("기업마당", "https://www.bizinfo.go.kr/sii/siia/selectSIIA200View.do", "https://www.bizinfo.go.kr")

def get_kotra():
    # KOTRA 무역투자24
    return fetch_and_filter_board("KOTRA", "https://www.kotra.or.kr/subList/20000020753", "https://www.kotra.or.kr")

def get_kepco():
    # 한전 에너지 이음
    return fetch_and_filter_board("한국전력", "https://www.kepco.co.kr/eum/program/introduceNotice/boardList.do", "https://www.kepco.co.kr")

# ---------------------------------------------------------
# [AI 분석 및 메인 실행 로직]
# ---------------------------------------------------------

def analyze_with_ai(item):
    """Gemini를 사용해 마감일, 적합성, 아이디어 추출"""
    prompt = f"""
    아래는 '{item['기관']}'의 사업 공고 제목과 상세 본문의 일부야.
    이 정보를 바탕으로 아래 3가지를 추출/작성해.

    제목: {item['사업명']}
    본문: {item['본문']}

    [요청사항]
    1. 신청기간: 본문에서 접수 마감일(예: 2026.04.23)을 찾아내. 못 찾으면 '상세링크 참조'라고 적어.
    2. 적합성: ICT/AI 기업 관점에서의 참여 적합성 (상/중/하 중 택1)
    3. 아이디어: 이 사업에 참여하기 위한 구체적인 액션 아이디어 1문장 (명사형 종결)

    [출력형식]
    반드시 '|' 기호로만 구분해서 딱 한 줄로만 대답해. 부연설명 금지.
    신청기간|적합성|아이디어
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
            raise ValueError("응답 형식 오류")
    except Exception as e:
        print(f"[{item['기관']}] AI 분석 에러: {e}")
        item['신청기간'] = "직접 확인"
        item['협회 적합성'] = "에러"
        item['제안 아이디어'] = "분석 실패"
        
    return item

def main():
    print("크롤링을 시작합니다...")
    
    # 각 기관별 크롤링 결과를 하나의 리스트로 합치기
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_nia())
    all_new_data.extend(get_iris())
    all_new_data.extend(get_bizinfo())
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

    print(f"총 {len(all_new_data)}개의 유효 공고를 AI로 분석합니다...")

    for item in all_new_data:
        item = analyze_with_ai(item)
        
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)

    if not processed_items:
        print("조건에 맞는 새 공고가 없습니다. 이메일을 발송하지 않습니다.")
        return

    # 출력 설정
    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '사업명', '신청기간', '협회 적합성', '제안 아이디어', '링크']]
    
    # 기관명 기준으로 정렬 (보기 좋게 묶어주기 위함)
    df = df.sort_values(by=['기관', '상태'])

    # HTML 표 디자인
    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [통합] ICT·AX 사업 공고 및 AI 인사이트
        </h2>
        <p style="color:#555; font-size:14px;">수집 채널: NIPA, NIA, IRIS, 기업마당, KOTRA, 한전</p>
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
        
    print("작업 완료! 이메일이 발송되었습니다.")

if __name__ == "__main__":
    main()
