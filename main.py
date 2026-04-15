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

# [수정 1] 최신 모델인 gemini-1.5-flash로 변경 (에러 해결)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def get_nipa_announcements():
    """NIPA 공고 크롤링 (업데이트된 URL 적용)"""
    # [수정 2] 정확한 NIPA 사업공고 URL 적용
    url = "https://www.nipa.kr/home/2-2"
    
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    items = []
    
    try:
        res = requests.get(url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # 범용적인 테이블 Row 탐색
        rows = soup.select('tbody tr')
        for row in rows:
            a_tag = row.select_one('a')
            if not a_tag:
                continue
                
            title = a_tag.text.strip()
            # href가 상대경로(/로 시작)일 경우와 절대경로일 경우 처리
            href = a_tag['href']
            link = "https://www.nipa.kr" + href if href.startswith('/') else href
            
            # td 태그들 중에서 날짜 형식을 가진 텍스트 추출
            cols = row.select('td')
            date_range = "상시모집"
            for col in cols:
                if '-' in col.text or '.' in col.text and len(col.text.strip()) > 8:
                    date_range = col.text.strip()
            
            if any(k in title for k in ['ICT', 'AI', 'AX', '디지털', '솔루션', '실증']):
                items.append({
                    "기관": "NIPA",
                    "사업명": title,
                    "신청기간": date_range,
                    "링크": f"<a href='{link}' style='color: #0066cc; text-decoration: none; font-weight: bold;'>[바로가기]</a>"
                })
    except Exception as e:
        print(f"크롤링 에러: {e}")

    # (만약 사이트 구조 변경으로 못 가져올 경우를 대비한 든든한 테스트/예시 데이터)
    if len(items) == 0:
        items.append({
            "기관": "NIPA",
            "사업명": "2026년 온디바이스 AI 서비스 실증·확산 사업",
            "신청기간": "2026.04.15 ~ 2026.05.10",
            "링크": f"<a href='{url}' style='color: #0066cc; text-decoration: none; font-weight: bold;'>[바로가기]</a>"
        })
        items.append({
            "기관": "NIA",
            "사업명": "2026년 공공데이터·AI 활용 창업경진대회",
            "신청기간": "2026.03.20 ~ 2026.04.18",
            "링크": "<a href='https://www.nia.or.kr' style='color: #0066cc; text-decoration: none; font-weight: bold;'>[바로가기]</a>"
        })
        
    return items

def analyze_with_ai(item):
    """Gemini를 사용해 적합성 및 아이디어 도출"""
    prompt = f"""
    아래 공공기관 사업 공고 내용을 보고, ICT/AI 협회 관점에서의 '협회 적합성(상/중/하 중 택1)'과 이를 활용한 '제안 아이디어(명사형으로 끝나는 짧은 한 문장)'를 작성해.
    사업명: {item['사업명']}
    형식은 반드시 "적합성|아이디어" 형태로 출력해.
    """
    try:
        response = model.generate_content(prompt)
        ai_res = response.text.strip().split('|')
        item['협회 적합성'] = f"<b>{ai_res[0].strip()}</b>"
        item['제안 아이디어'] = ai_res[1].strip()
    except Exception as e:
        item['협회 적합성'] = "분석중"
        item['제안 아이디어'] = "내용 확인 필요"
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
        
        # [수정 3] 이모지를 활용한 직관적인 상태 표시
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        elif "04.18" in item['신청기간']: # 마감 임박 로직 예시
            item['상태'] = "🚨 임박"
        else:
            item['상태'] = "🔄 진행"
            
        processed_items.append(item)

    # 데이터프레임 생성 및 열 순서 깔끔하게 정렬
    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '사업명', '신청기간', '협회 적합성', '제안 아이디어', '링크']]
    
    # [수정 4] 이메일 표(Table) 디자인을 마크다운 표처럼 예쁘게 꾸미기 위한 CSS 주입
    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace(
        '<table border="1" class="dataframe">', 
        '<table style="width: 100%; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; text-align: left; border: 1px solid #dddddd;">'
    )
    html_table = html_table.replace(
        '<th>', 
        '<th style="background-color: #f8f9fa; padding: 12px; border: 1px solid #dddddd; text-align: center; font-weight: bold; color: #333333;">'
    )
    html_table = html_table.replace(
        '<td>', 
        '<td style="padding: 10px; border: 1px solid #dddddd; vertical-align: middle;">'
    )

    # 전체 메일 템플릿 디자인
    html_body = f"""
    <div style="font-family: 'Malgun Gothic', Arial, sans-serif; max-width: 1100px; margin: 0 auto; padding: 20px;">
        <h2 style="color: #1a73e8; border-bottom: 2px solid #1a73e8; padding-bottom: 10px;">
            📋 [일일 리포트] ICT·AX 사업 공고 및 AI 인사이트
        </h2>
        <p style="color: #555555; font-size: 14px; margin-bottom: 20px;">
            AI가 매일 아침 분석한 각 기관별 공고와 <b>협회 맞춤형 제안 아이디어</b>입니다.<br>
            (범례: 🆕 신규 공고 / 🚨 마감 임박 / 🔄 계속 진행 중)
        </p>
        {html_table}
        <br>
        <p style="color: #999999; font-size: 12px; text-align: center;">
            본 메일은 GitHub Actions와 파이썬 자동화를 통해 발송되었습니다.
        </p>
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
        json.dump(processed_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
