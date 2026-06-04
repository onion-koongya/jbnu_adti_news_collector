import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import gspread

# =========================================================================
# API 키 설정 (네이버만 사용)
# =========================================================================
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

def search_naver_news(query):
    """네이버 뉴스 API 검색"""
    enc_text = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    
    res = requests.get(url, headers=headers)
    if res.status_code == 200:
        return res.json().get("items", [])
    return []

def extract_og_image(url):
    """기사 원본 이미지 추출"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]
    except:
        pass
    return None

def main():
    # 검색 키워드
    keywords = [
        "강은호 전북대", "장원준 전북대", "송문원 전북대", 
        "이대규 전북대", "유준수 전북대", "전광호 전북대", "홍성민 전북대"
    ]
    
    all_items = []
    print("⚡ 네이버 뉴스 검색 시작...")
    for kw in keywords:
        all_items.extend(search_naver_news(kw))

    # 중복 기사 제거
    seen_links = set()
    unique_items = []
    for item in all_items:
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            unique_items.append(item)

    db_data = {"언론보도": [], "기고": []}
    news_idx = 1
    opinion_idx = 1
    
    # 🚨 에러가 났던 부분: 여기서 교수님 명단을 확실하게 파이썬에게 알려줍니다.
    prof_names = ["강은호", "장원준", "송문원", "이대규", "유준수", "전광호", "홍성민"]

    for item in unique_items:
        pub_date = item.get("pubDate", "")
        # 올해(2026년) 기사만 통과
        if " 2026 " not in pub_date:
            continue

        title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")

        # 1. 블랙리스트 필터링 적용
        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "선대위", "공천", "출사", "재보궐", "김어준","더불어민주당"]
        if any(bad_word in title or bad_word in description for bad_word in bad_keywords):
            continue

        # =================================================================
        # 2. [핵심] 수집은 다 하되, 메인 기사에만 별표(**) 달기
        # =================================================================
        is_main_article = False
        for name in prof_names:
            name_in_title = title.count(name)
            name_in_desc = description.count(name)
            
            # 제목에 대놓고 있거나, 합쳐서 2번 이상 나오면 메인 기사로 인정
            if name_in_title >= 1 or (name_in_title + name_in_desc) >= 2:
                is_main_article = True
                break 
                
        # 기사를 버리지 않고, 조건에 맞을 때만 제목을 수정합니다.
        if is_main_article:
            title = f"** {title}" 
        # =================================================================

        target_link = item.get("link", "")
        is_opinion = any(word in title for word in ["칼럼", "기고", "시론", "포럼", "특별기고"])

        img_url = extract_og_image(target_link)
        img_formula = f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음"

        row_data = {
            "제목": title,
            "링크": target_link,
            "작성일": pub_date,
            "이미지보기": img_formula,
        }

        if is_opinion:
            row_data["번호"] = opinion_idx
            db_data["기고"].append(row_data)
            opinion_idx += 1
        else:
            row_data["번호"] = news_idx
            db_data["언론보도"].append(row_data)
            news_idx += 1

    # =========================================================================
    # 구글 스프레드시트 업데이트
    # =========================================================================
    GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
    if GOOGLE_CREDENTIALS and (db_data["언론보도"] or db_data["기고"]):
        try:
            creds = json.loads(GOOGLE_CREDENTIALS)
            gc = gspread.service_account_from_dict(creds)
            
            sh = gc.open("방위산업 뉴스 DB") 
            
            for sheet_name in ["언론보도", "기고"]:
                if db_data[sheet_name]:
                    ws = sh.worksheet(sheet_name)
                    ws.clear()
                    df = pd.DataFrame(db_data[sheet_name])
                    df = df[["번호", "제목", "링크", "작성일", "이미지보기"]]
                    ws.update(
                        range_name="A1", 
                        values=[df.columns.values.tolist()] + df.astype(str).values.tolist(), 
                        value_input_option="USER_ENTERED"
                    )
            print("✔ 구글 시트 업데이트 완벽 성공!")
        except Exception as e:
            print(f"❌ 구글 시트 동기화 실패: {e}")

if __name__ == "__main__":
    main()
