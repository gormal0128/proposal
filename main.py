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

def get_nipa_announcements():
    """NIPA 목록 + 상세페이지 본문 크롤링"""
    url = "https://www.nipa.kr/home/2-2"
    headers = {'User-Agent': 'Mozilla/5.0'}
    items = []
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        rows = soup.select('tbody tr')
        
        for row in rows:
            a_tag = row.select_one('a')
            if not a_tag: continue
                
            title = a_tag.text.strip()
            href = a_tag['href']
            link = "https://www.nipa.kr" + href if href.startswith('/') else href
            
            # [핵심 1] 불필요한 공고 제목 필터링 (결과, 안내, 취소 등 제외)
            exclude_keywords = ['결과', '안내', '사전규격', '입찰', '취소', '연기', '설명회']
            if any(ext in title for ext in exclude_keywords):
                continue
            
            # 타겟 키워드가 있는 공고만 상세페이지 진입
            if any(k in title for k in ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증', '모집', '지원']):
                # [핵심 2] 상세 페이지 진입하여 본문 텍스트 가져오기
                try:
                    detail_res = requests.get(link, headers=headers)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    # NIPA 상세 본문 영역을 대략적으로 잡아 텍스트 추출 (앞부분 1500자만 AI에게 전달)
                    content_text = detail_soup.text
                    content_text = ' '.join(content_text.split())[:1500] 
                except:
                    content_text = "본문 로드 실패"

                items.append({
                    "기관": "NIPA",
                    "사업명": title,
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>",
                    "본문": content_text # AI에게 전달할 데이터
                })
    except Exception as e:
        print(f"크롤링 에러: {e}")
        
    return items

def analyze_with_ai(item):
    """Gemini를 사용해 마감일, 적합성, 아이디어 한 번에 추출"""
    prompt = f"""
    아래는 공공기관 사업 공고의 '제목'과 '상세 본문'의 일부야.
    이 정보를 바탕으로 아래 3가지를 추출 및 작성해.

    제목: {item['사업명']}
    본문: {item['본문']}

    [요청사항]
    1. 신청기간: 본문에서 접수 마감일이나 신청 기간을 찾아내서 기입해. (예: 2026.04.12 ~ 04.23) 찾을 수 없으면 '링크 확인'이라고 적어.
    2. 적합성: ICT/AI 협회 관점에서의 참여 적합성 (상/중/하 중 택1)
    3. 아이디어: 이 사업을 활용해 협회가 할 수 있는 액션 아이디어 1문장

    [출력형식]
    반드시 아래처럼 '|' 기호로만 구분해서 딱 한 줄로만 대답해. 다른 부연설명은 절대 금지.
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
            raise ValueError("AI 응답 형식 오류")
    except Exception as e:
        print(f"AI 분석 에러: {e}")
        item['신청기간'] = "직접 확인"
        item['협회 적합성'] = "에러"
        item['제안 아이디어'] = "분석 실패 (로그 확인)"
        
    return item

def main():
    new_data = get_nipa_announcements()
    
    db_file = 'prev_data.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
    else:
        prev_data = []

    processed_items = []
    prev_titles = [d.get('사업명', '') for d in prev_data]

    for item in new_data:
        item = analyze_with_ai(item)
        
        # 상태 표시 로직
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)

    if not processed_items:
        print("조건에 맞는 새 공고가 없습니다.")
        return

    # 출력할 항목만 선택 (본문은 메일 표에서 제외)
    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '사업명', '신청기간', '협회 적합성', '제안 아이디어', '링크']]
    
    # HTML 표 디자인
    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f8f9fa; padding: 12px; border: 1px solid #ddd; text-align: center; font-weight: bold;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

    html_body = f"""
    <div style="font-family: 'Malgun Gothic', sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [일일 리포트] ICT·AX 사업 공고 및 AI 인사이트
        </h2>
        {html_table}
    </div>
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] ICT·AX 사업 공고 리포트"
    msg['To'] = RECEIVER_EMAIL
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        # 본문은 용량을 많이 차지하므로 DB 저장 시 제외
        for d in processed_items:
            d.pop('본문', None)
        json.dump(processed_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
