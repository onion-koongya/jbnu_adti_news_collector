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

        raw_title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")
        full_text = raw_title + " " + description

        # 1. 노이즈 블랙리스트 
        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "선대위", "공천", "출사", "재보궐", "김어준", "안도걸", "총학생회", "등록금", "의대", "입학"]
        if any(bad_word in full_text for bad_word in bad_keywords):
            continue

        # 2. 방위산업 무관 기사 컷 (필수 단어 없으면 버림)
        defense_keywords = ["방산", "방위", "국방", "무기", "전력", "안보", "군수", "K-방산", "국방사업"]
        if not any(d_word in full_text for d_word in defense_keywords):
            continue

        # =================================================================
        # 💡 [핵심] 3. 신원 확인 투트랙(Two-Track) 필터
        # =================================================================
        target_names = ["강은호", "장원준", "송문원", "이대규", "유준수", "전광호", "홍성민", "첨단방위산업학과"]
        
        # 트랙 A: 타겟 인물/학과가 언급된 기사인가?
        has_target = any(name in full_text for name in target_names)
        
        # 트랙 B: 타겟 이름은 없지만, 제목에 '전북대'와 '방산(국방 등)'이 명확히 적힌 메인 보도인가?
        is_jbnu_defense_title = any(univ in raw_title for univ in ["전북대", "전북대학교"]) and \
                                any(d_word in raw_title for d_word in defense_keywords)
                                
        # A와 B 둘 다 해당 안 되면 "전북방산", "이란 미사일" 등 불순물이므로 가차 없이 버림!
        if not (has_target or is_jbnu_defense_title):
            continue
        # =================================================================

        # 4. 별표(**) 승격 심사
        is_main_article = False
        for keyword in star_keywords:
            count_in_title = raw_title.count(keyword)
            count_in_desc = description.count(keyword)
            if count_in_title >= 1 or (count_in_title + count_in_desc) >= 2:
                is_main_article = True
                break 

        # =================================================================
        # 5. 스마트 중복 제거 (단어 70% OR 글자 90%)
        # =================================================================
        is_duplicate = False
        for prev_title, prev_is_main in saved_titles:
            word_sim = get_word_overlap_ratio(raw_title, prev_title)
            char_sim = difflib.SequenceMatcher(None, raw_title, prev_title).ratio()
            
            # 조건이 강화되었습니다!
            if word_sim >= 0.7 or char_sim >= 0.9: 
                if is_main_article == prev_is_main:
                    is_duplicate = True
                    break
                elif not is_main_article and prev_is_main:
                    is_duplicate = True
                    break
                
        if is_duplicate:
            continue 
        # =================================================================
            
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
