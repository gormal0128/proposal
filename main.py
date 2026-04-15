import os
import json
import requests
from bs4 import BeautifulSoup
import pandas as pd
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re # [추가] 텍스트에서 날짜만 정확히 뽑아내는 정규표현식 라이브러리

# 환경 변수 설정
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")

TARGET_AGENCIES = ["NIPA", "기업마당", "NIA", "IRIS", "KOTRA", "한국전력"]
TARGET_KEYWORDS = ['AI', 'AX', 'ICT', '실증', '시범', '테스트베드', '데이터', '스마트공장', '디지털전환', '수출', '스마트시티']

def fetch_and_filter_board(agency_name, board_url, base_url, css_selector='tbody tr'):
    """기관별 게시판 크롤링 및 날짜 직접 추출"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
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
            
            matched_kws = [k for k in TARGET_KEYWORDS if k.upper() in title.upper()]
            
            if matched_kws:
                # ----------------------------------------------------
                # [핵심 변경] 상세페이지에 직접 접속해서 날짜 텍스트를 뜯어옵니다.
                # ----------------------------------------------------
                try:
                    detail_res = requests.get(link, headers=headers, timeout=10)
                    detail_soup = BeautifulSoup(detail_res.text, 'html.parser')
                    
                    # 태그를 제외한 순수 텍스트만 가져옴
                    detail_text = detail_soup.get_text(separator=' ') 
                    
                    # 1. 신청기간 추출 (정규표현식 사용)
                    # "신청기간" 글자 뒤에 나오는 "0000.00.00 ~ 0000.00.00" 형태의 패턴을 찾음
                    period_match = re.search(r'신청기간\s*[:|]?\s*([0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2}.*?(?:~|-).*?[0-9]{4}[-.\/][0-9]{2}[-.\/][0-9]{2})', detail_text)
                    sinchung = period_match.group(1).strip() if period_match else "상세 본문 참조"
                    
                    # 2. 공고일 추출
                    # 웹페이지 상단(작성자 이름 옆 등)에 등장하는 첫 번째 날짜 포맷을 공고일로 간주
                    dates = re.findall(r'\b202[0-9][-.\/][0-1][0-9][-.\/][0-3][0-9]\b', detail_text)
                    gongo = dates[0] if dates else "확인필요"
                    
                except:
                    gongo = "로드 실패"
                    sinchung = "로드 실패"

                items.append({
                    "기관": agency_name,
                    "매칭 키워드": ", ".join(matched_kws),
                    "사업명": title,
                    "공고일": gongo,
                    "신청기간": sinchung,
                    "링크": f"<a href='{link}' style='color: #0066cc; font-weight: bold;'>[바로가기]</a>"
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


def main():
    print("통합 크롤링 시작...")
    
    all_new_data = []
    all_new_data.extend(get_nipa())
    all_new_data.extend(get_bizinfo())
    all_new_data.extend(get_nia())
    all_new_data.extend(get_iris())
    all_new_data.extend(get_kotra())
    all_new_data.extend(get_kepco())
    
    # DB 비교 로직 (기존과 동일)
    db_file = 'prev_data.json'
    if os.path.exists(db_file):
        with open(db_file, 'r', encoding='utf-8') as f:
            prev_data = json.load(f)
    else:
        prev_data = []

    processed_items = []
    prev_titles = [d.get('사업명', '') for d in prev_data]
    found_agencies = set()

    for item in all_new_data:
        found_agencies.add(item['기관'])
        if item['사업명'] not in prev_titles:
            item['상태'] = "🆕 신규"
        else:
            item['상태'] = "🔄 진행"
        processed_items.append(item)

    # 검색 결과가 없는 기관 처리
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

    # 출력 설정
    df = pd.DataFrame(processed_items)
    df = df[['상태', '기관', '매칭 키워드', '사업명', '공고일', '신청기간', '링크']]
    df['sort_order'] = df['상태'].apply(lambda x: 1 if x in ['🆕 신규', '🔄 진행'] else 2)
    df = df.sort_values(by=['sort_order', '기관'])
    df = df.drop(columns=['sort_order'])

    html_table = df.to_html(index=False, escape=False)
    html_table = html_table.replace('<table border="1" class="dataframe">', '<table style="width: 100%; border-collapse: collapse; font-family: Arial; font-size: 13px; text-align: left; border: 1px solid #ddd;">')
    html_table = html_table.replace('<th>', '<th style="background-color: #f3f6fc; padding: 12px; border: 1px solid #ccc; text-align: center; font-weight: bold; color:#1a73e8; white-space: nowrap;">')
    html_table = html_table.replace('<td>', '<td style="padding: 10px; border: 1px solid #ddd; vertical-align: middle;">')

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
    
    # [수정된 부분] 쉼표로 구분된 이메일을 리스트로 쪼개고 빈칸을 제거합니다.
    receiver_list = [email.strip() for email in RECEIVER_EMAIL.split(',')]
    
    # 메일 봉투(헤더)에는 쉼표로 연결해서 보여줍니다.
    msg['To'] = ", ".join(receiver_list) 
    msg.attach(MIMEText(html_body, 'html'))
    
    with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
        smtp.login(EMAIL_USER, EMAIL_PASS)
        # 실제 발송(sendmail) 시에는 쪼개진 '리스트' 형태를 전달해야 모두에게 발송됩니다.
        smtp.sendmail(EMAIL_USER, receiver_list, msg.as_string())

    with open(db_file, 'w', encoding='utf-8') as f:
        valid_items = [d for d in processed_items if d['상태'] != '-']
        json.dump(valid_items, f, ensure_ascii=False, indent=4)

if __name__ == "__main__":
    main()
