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

# 1. 환경 변수 설정 (GitHub Secrets에서 가져옴)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-pro')

def get_nipa_announcements():
    """NIPA 공고 크롤링 예시"""
    url = "https://www.nipa.kr/main/selectBbsNttList.do?bbsId=BBS0000002"
    res = requests.get(url)
    soup = BeautifulSoup(res.text, 'html.parser')
    items = []
    
    # 실제 사이트 구조에 맞게 select 문 수정 필요
    rows = soup.select('table.board-list tbody tr')
    for row in rows:
        title = row.select_one('.subject').text.strip()
        link = "https://www.nipa.kr" + row.select_one('a')['href']
        date_range = row.select_one('.date').text.strip() # 예: 2026.04.01 ~ 2026.04.30
        
        # ICT/AX 관련 키워드 필터링
        if any(k in title for k in ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증']):
            items.append({
                "기관": "NIPA",
                "사업명": title,
                "신청기간": date_range,
                "링크": link
            })
    return items

def analyze_with_ai(item):
    """Gemini를 사용해 적합성 및 아이디어 도출"""
    prompt = f"""
    아래 공고 내용을 보고 '협회 적합성(상/중/하)'과 '제안 아이디어(한 문장)'를 작성해줘.
    공고: {item['사업명']}
    형식: 적합성|아이디어
    """
    try:
        response = model.generate_content(prompt)
        ai_res = response.text.split('|')
        item['협회 적합성'] = ai_res[0].strip()
        item['제안 아이디어'] = ai_res[1].strip()
    except:
        item['협회 적합성'] = "분석실패"
        item['제안 아이디어'] = "내용 확인 필요"
    return item

def main():
    # 데이터 수집
    new_data = get_nipa_announcements() # 다른 기관 함수도 여기 추가
    
    # 이전 데이터 로드 (신규/변경 확인용)
    db_file = 'prev_data.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
    else:
        prev_data = []

    # AI 분석 및 상태 표시
    processed_items = []
    prev_titles = [d['사업명'] for d in prev_data]

    for item in new_data:
        item = analyze_with_ai(item)
        
        # 신규 여부 확인
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "-"
            
        # 마감 임박 확인 (오늘 기준 3일 이내 예시)
        item['마감임박'] = "🚨" if "04.18" in item['신청기간'] else "" # 로직 실제 구현 필요
        
        processed_items.append(item)

    # 이메일 발송 로직 (HTML 표 생성)
    df = pd.DataFrame(processed_items)
    html_table = df.to_html(index=False, escape=False, justify='center')
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] ICT·AX 사업 공고 리포트"
    msg.attach(MIMEText(html_table, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    # 최신 데이터 저장
    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(processed_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
