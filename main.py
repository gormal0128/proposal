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

# 1. 환경 변수 설정
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_nipa_announcements():
    """NIPA 공고 크롤링"""
    url = "https://www.nipa.kr/main/selectBbsNttList.do?bbsId=BBS0000002"
    
    # 웹사이트 차단을 막기 위한 가짜 User-Agent
    headers = {'User-Agent': 'Mozilla/5.0'}
    items = []
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 임시 크롤링 로직 (실제 사이트 구조에 맞게 수정 필요)
        rows = soup.select('table.board-list tbody tr')
        for row in rows:
            title = row.select_one('.subject').text.strip()
            link = "https://www.nipa.kr" + row.select_one('a')['href']
            date_range = row.select_one('.date').text.strip()
            
            if any(k in title for k in ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증']):
                items.append({
                    "기관": "NIPA",
                    "사업명": title,
                    "신청기간": date_range,
                    "링크": f"<a href='{link}'>[링크]</a>"
                })
    except Exception as e:
        print(f"크롤링 에러: {e}")

    # [수정된 부분] 크롤링된 데이터가 없으면 '테스트 데이터'를 강제로 집어넣습니다.
    if len(items) == 0:
        items.append({
            "기관": "NIPA (테스트)",
            "사업명": "[테스트] 2026년 유망 ICT·AX 기업 글로벌 진출 지원사업",
            "신청기간": "2026.04.15 ~ 2026.05.10",
            "링크": "<a href='https://www.nipa.kr'>[바로가기]</a>"
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
    except Exception as e:
        item['협회 적합성'] = "분석실패"
        item['제안 아이디어'] = f"에러: {e}"
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
        
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "-"
            
        item['마감임박'] = "🚨" if "04.18" in item['신청기간'] else "-"
        processed_items.append(item)

    df = pd.DataFrame(processed_items)
    
    # 표 디자인을 조금 더 보기 좋게 꾸밉니다
    html_table = df.to_html(index=False, escape=False, justify='center')
    html_body = f"""
    <h2>오늘의 ICT·AX 공고 리포트</h2>
    <p>AI가 분석한 추천 아이디어와 적합성입니다.</p>
    {html_table}
    """
    
    msg = MIMEMultipart()
    msg['Subject'] = f"[{datetime.date.today()}] ICT·AX 사업 공고 리포트"
    msg['To'] = RECEIVER_EMAIL # [수정된 부분] 받는 사람 이름이 표시되도록 추가!
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        smtp.sendmail(EMAIL_USER, RECEIVER_EMAIL, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        json.dump(processed_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
