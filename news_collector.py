import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json
import gspread
import difflib

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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
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
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            with open(os.path.join(IMAGE_DIR, filename), "wb") as f:
                f.write(res.content)
            return True
    except:
        pass
    return False

def main():
    keywords = [
        "강은호 전북대", "장원준 전북대", "송문원 전북대", 
        "이대규 전북대", "유준수 전북대", "전광호 전북대", "홍성민 전북대", "전북대", "전북대학교 첨단방위산업학과"
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
        "전북대", "첨단방위산업학과"
    ]
    
    print(f" 총 {len(unique_items)}개의 뉴스 발견. 스마트 필터링 가동...")

    # 💡 [핵심 변경] 수첩에 '제목'과 '별표 여부'를 짝지어서 저장합니다.
    saved_titles = [] 
    
    for item in unique_items:
        pub_date = item.get("pubDate", "")
        if " 2026 " not in pub_date:
            continue

        raw_title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")

        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "선대위", "공천", "출사", "재보궐", "김어준", "안도걸"]
        if any(bad_word in raw_title or bad_word in description for bad_word in bad_keywords):
            continue

        # =================================================================
        # 💡 [핵심 추가] 3. 화이트리스트 (방산 관련 필수 키워드가 없으면 무조건 버림)
        # =================================================================
        defense_keywords = ["방산", "방위", "국방", "무기", "전력", "안보", "군수", "드론", "항공", "K-방산"]
        # 기사 제목이나 요약문에 위 단어가 단 하나도 포함되어 있지 않다면? -> 곁다리 기사로 간주하고 삭제!
        if not any(d_word in raw_title or d_word in description for d_word in defense_keywords):
            continue

        # =================================================================
        # 💡 [핵심 추가] 4. 소속 대학 화이트리스트 (타 대학 철벽 방어)
        # =================================================================
        univ_keywords = ["전북대", "전북대학교"]
        # 기사 제목이나 요약문에 "전북대"나 "전북대학교"가 없으면 남의 학교 기사로 간주하고 삭제!
        if not any(u_word in raw_title or u_word in description for u_word in univ_keywords):
            continue

        # =================================================================
        # 1. 메인 기사(별표 대상) 판별 로직 강화 (제목 + 요약본 쌍끌이)
        # =================================================================
        is_main_article = False
        for keyword in star_keywords:
            count_in_title = raw_title.count(keyword)
            count_in_desc = description.count(keyword)
            
            # 제목에 1번 이상 대놓고 있거나, 제목과 요약 합쳐서 2번 이상 나오면 메인 기사로 승격!
            if count_in_title >= 1 or (count_in_title + count_in_desc) >= 2:
                is_main_article = True
                break 

        # =================================================================
        # 2. 스마트 중복 제거 (VIP 기사 보호)
        # =================================================================
        is_duplicate = False
        for prev_title, prev_is_main in saved_titles:
            similarity = difflib.SequenceMatcher(None, raw_title, prev_title).ratio()
            
            if similarity >= 0.8:
                # 둘 다 일반 기사이거나 둘 다 별표 기사면 -> 진짜 중복 컷
                if is_main_article == prev_is_main:
                    is_duplicate = True
                    break
                # 기존 기사는 '별표'인데, 새 기사가 '일반'이면 -> 퀄리티 낮으므로 컷
                elif not is_main_article and prev_is_main:
                    is_duplicate = True
                    break
                # 💡 핵심: 기존 기사는 '일반'인데, 새 기사가 '별표'면? -> 안 버리고 통과!
                
        if is_duplicate:
            continue 
            
        # 통과한 기사는 수첩에 (제목, 별표여부) 세트로 기록
        saved_titles.append((raw_title, is_main_article))
        
        # 별표 추가
        final_title = f"** {raw_title}" if is_main_article else raw_title
        # =================================================================

        target_link = item.get("link", "")
        is_opinion = any(word in final_title for word in ["칼럼", "기고", "시론", "포럼", "특별기고"])

        if is_opinion:
            file_name = f"opinion_{opinion_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 

            db_data["기고"].append({
                "번호": opinion_idx,
                "제목": final_title,
                "링크": target_link,
                "작성일": pub_date,
                "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음",
            })
            opinion_idx += 1
        else:
            file_name = f"news_{news_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 

            db_data["언론보도"].append({
                "번호": news_idx,
                "제목": final_title,
                "링크": target_link,
                "작성일": pub_date,
                "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음",
            })
            news_idx += 1

    # 별표 우선 정렬 및 번호 매기기
    for sheet_name in ["언론보도", "기고"]:
        db_data[sheet_name].sort(key=lambda x: not x["제목"].startswith("**"))
        for idx, row in enumerate(db_data[sheet_name], start=1):
            row["번호"] = idx

    # 구글 스프레드시트 데이터 전송
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
            
    # 로컬 백업 유지
    if db_data["언론보도"] or db_data["기고"]:
        with pd.ExcelWriter("언론보도_기고칼럼_db.xlsx", engine="openpyxl") as writer:
            if not pd.DataFrame(db_data["언론보도"]).empty:
                pd.DataFrame(db_data["언론보도"]).to_excel(writer, sheet_name="언론보도", index=False)
            if not pd.DataFrame(db_data["기고"]).empty:
                pd.DataFrame(db_data["기고"]).to_excel(writer, sheet_name="기고", index=False)

if __name__ == "__main__":
    main()
