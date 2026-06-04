import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import gspread
import difflib
import re

# =========================================================================
# API 키 설정
# =========================================================================
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

IMAGE_DIR = "news_images"
os.makedirs(IMAGE_DIR, exist_ok=True)

def search_naver_news(query):
    enc_text = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=100&sort=date"
    headers = {"X-Naver-Client-Id": CLIENT_ID, "X-Naver-Client-Secret": CLIENT_SECRET}
    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("items", [])
    return []

def extract_og_image(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]
    except:
        pass
    return None

def download_image(url, filename):
    if not url: return False
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            with open(os.path.join(IMAGE_DIR, filename), "wb") as f:
                f.write(res.content)
            return True
    except:
        pass
    return False

def get_word_overlap_ratio(title1, title2):
    """두 제목의 단어 교집합 비율을 계산합니다."""
    words1 = set(re.findall(r'\w+', title1))
    words2 = set(re.findall(r'\w+', title2))
    if not words1 or not words2: return 0.0
    common_words = words1.intersection(words2)
    return len(common_words) / min(len(words1), len(words2))

def main():
    # 검색어는 넓게 던져서 최대한 긁어옵니다 (필터링은 파이썬이 알아서 컷)
    keywords = [
        "전북대 방산", "전북대 국방", "전북대 방위산업", 
        "강은호 전북대", "장원준 전북대", "송문원 전북대", 
        "이대규 전북대", "유준수 전북대", "전광호 전북대", "홍성민 전북대", "첨단방위산업학과"
    ]
    all_items = []
    print("⚡ 네이버 뉴스 검색 시작...")
    for kw in keywords:
        all_items.extend(search_naver_news(kw))

    seen_links = set()
    unique_items = []
    for item in all_items:
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            unique_items.append(item)

    db_data = {"언론보도": [], "기고": []}
    news_idx = 1
    opinion_idx = 1
    
    star_keywords = [
        "강은호", "장원준", "송문원", "이대규", "유준수", "전광호", "홍성민", 
        "첨단방위산업학과", "방위산업학과", "전북대"
    ]
    
    print(f" 총 {len(unique_items)}개의 뉴스 발견. 필터링 중...")

    saved_titles = [] 
    
    for item in unique_items:
        pub_date = item.get("pubDate", "")
        if " 2026 " not in pub_date:
            continue
# 기존 텍스트 추출 코드
       # 기존 텍스트 추출 코드
        raw_title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")
        full_text = raw_title + " " + description
        compressed_text = full_text.replace(" ", "")

        # =================================================================
        # 💡 [최종 픽스] VIP 무적 프리패스 & 대학 보도자료 맞춤형 필터
        # =================================================================
        prof_keywords = ["강은호", "장원준", "송문원", "이대규", "유준수", "전광호", "홍성민"]
        # 학과를 지칭할 수 있는 다양한 표현들을 넉넉히 넣습니다.
        dept_keywords = ["첨단방위산업학과", "방위산업학과", "국방사업관리", "방산 전문인력", "방산 인재"]
        
        # 정치 노이즈 블랙리스트 (의대, 입학 등은 대학 보도자료 통과를 위해 제외함)
        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "공천", "재보궐", "김어준", "여론조사", "더불어민주당", "국민의힘"]

        is_prof_mentioned = any(p in full_text for p in prof_keywords)
        is_dept_mentioned = any(d in full_text for d in dept_keywords)

        # 1. VIP 무적 프리패스 (블랙리스트 면제!)
        if is_prof_mentioned or is_dept_mentioned:
            pass # 교수님이나 학과 소식이면 블랙리스트 묻지도 따지지도 않고 무조건 100% 수집!
            
        # 2. 교수/학과 언급은 없지만, 대학 차원의 '전북대 방산' 일반 기사인 경우
        else:
            is_general_defense = any(u in raw_title for u in ["전북대", "전북대학교"]) and \
                                 any(d in raw_title for d in ["방산", "국방", "방위", "무기", "K-방산", "방사청"])
            
            if not is_general_defense:
                continue # 전북대 방산 관련도 아니면 즉시 폐기!

            # 일반 보도는 정치 노이즈가 섞였을 수 있으므로 여기서만 블랙리스트 검사
            if any(b in compressed_text for b in bad_keywords):
                continue
        # =================================================================

        # =================================================================
        # 3. 별표(**) 승격 심사 (확실하게 부여)
        # =================================================================
        is_main_article = False
        
        # 교수님이 언급되었거나, 제목에 대놓고 학과 관련 단어가 있으면 무조건 별표!
        if is_prof_mentioned:
            is_main_article = True
        elif any(d in raw_title for d in dept_keywords):
            is_main_article = True
        # =================================================================

        # 4. 스마트 중복 제거 (단어 70% OR 글자 90%)
        is_duplicate = False
        for prev_title, prev_is_main in saved_titles:
            word_sim = get_word_overlap_ratio(raw_title, prev_title)
            char_sim = difflib.SequenceMatcher(None, raw_title, prev_title).ratio()
            
            if word_sim >= 0.7 or char_sim >= 0.9: 
                if is_main_article == prev_is_main:
                    is_duplicate = True
                    break
                elif not is_main_article and prev_is_main:
                    is_duplicate = True
                    break
                
        if is_duplicate:
            continue 
            
        saved_titles.append((raw_title, is_main_article))
        final_title = f"** {raw_title}" if is_main_article else raw_title

        target_link = item.get("link", "")
        is_opinion = any(word in final_title for word in ["칼럼", "기고", "시론", "포럼", "특별기고"])

        if is_opinion:
            file_name = f"opinion_{opinion_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 
            db_data["기고"].append({"번호": opinion_idx, "제목": final_title, "링크": target_link, "작성일": pub_date, "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음"})
            opinion_idx += 1
        else:
            file_name = f"news_{news_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 
            db_data["언론보도"].append({"번호": news_idx, "제목": final_title, "링크": target_link, "작성일": pub_date, "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음"})
            news_idx += 1

    for sheet_name in ["언론보도", "기고"]:
        db_data[sheet_name].sort(key=lambda x: not x["제목"].startswith("**"))
        for idx, row in enumerate(db_data[sheet_name], start=1):
            row["번호"] = idx

    GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")
    if GOOGLE_CREDENTIALS and (db_data["언론보도"] or db_data["기고"]):
        try:
            print("\n🚀 구글 스프레드시트 업데이트 시작...")
            creds = json.loads(GOOGLE_CREDENTIALS)
            gc = gspread.service_account_from_dict(creds)
            sh = gc.open("언론보도_기고칼럼_db")
            
            ws_news = sh.worksheet("언론보도")
            try: ws_news.clear()
            except: pass
            df_news = pd.DataFrame(db_data["언론보도"])
            if not df_news.empty:
                ws_news.update(range_name="A1", values=[df_news.columns.values.tolist()] + df_news.astype(str).values.tolist(), value_input_option="USER_ENTERED")
                
            ws_opinion = sh.worksheet("기고")
            try: ws_opinion.clear()
            except: pass
            df_opinion = pd.DataFrame(db_data["기고"])
            if not df_opinion.empty:
                ws_opinion.update(range_name="A1", values=[df_opinion.columns.values.tolist()] + df_opinion.astype(str).values.tolist(), value_input_option="USER_ENTERED")
            
            print("✔ 구글 스프레드시트 실시간 동기화 완료!")
        except Exception as e:
            print(f"❌ 구글 시트 동기화 실패: {e}")
            
    if db_data["언론보도"] or db_data["기고"]:
        with pd.ExcelWriter("언론보도_기고칼럼_db.xlsx", engine="openpyxl") as writer:
            if not pd.DataFrame(db_data["언론보도"]).empty:
                pd.DataFrame(db_data["언론보도"]).to_excel(writer, sheet_name="언론보도", index=False)
            if not pd.DataFrame(db_data["기고"]).empty:
                pd.DataFrame(db_data["기고"]).to_excel(writer, sheet_name="기고", index=False)

if __name__ == "__main__":
    main()
