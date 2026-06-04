import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd
import json      # 구글 인증용
import gspread   # 구글 스프레드시트용
import difflib  # 문자열 유사도 검사용 도구

# =========================================================================
# [설정] 발급받으신 네이버 API 정보를 여기에 입력하세요.
# =========================================================================
CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

# 저장할 이미지 폴더 생성
IMAGE_DIR = "news_images"
os.makedirs(IMAGE_DIR, exist_ok=True)


def search_naver_news(query):
    """네이버 뉴스 API를 통해 검색 결과를 가져옵니다."""
    enc_text = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc_text}&display=100&sort=date"

    headers = {
        "X-Naver-Client-Id": CLIENT_ID,
        "X-Naver-Client-Secret": CLIENT_SECRET,
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        return response.json().get("items", [])
    else:
        print(f"네이버 API 호출 실패 (에러 코드: {response.status_code})")
        return []


def extract_og_image(url):
    """기사 링크에서 대표 이미지(og:image) URL을 추출합니다."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, "html.parser")
            og_image = soup.find("meta", property="og:image")
            if og_image and og_image.get("content"):
                return og_image["content"]
    except Exception as e:
        print(f"링크 접속 실패 ({url}): {e}")
    return None


def download_image(url, filename):
    """이미지 URL에서 이미지를 다운로드하여 지정된 이름으로 저장합니다."""
    if not url:
        return False
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            with open(os.path.join(IMAGE_DIR, filename), "wb") as f:
                f.write(res.content)
            return True
        else:
            print(f"이미지 접근 거부됨 (상태 코드: {res.status_code})")
    except Exception as e:
        print(f"이미지 다운로드 에러: {e}")
        
    return False


def main():
    # 검색 키워드 
    keywords = [
        "강은호 전북대", "장원준 전북대", "송문원 전북대", 
        "이대규 전북대", "유준수 전북대", "전광호 전북대", "홍성민 전북대", "첨단방위산업학과"
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

    # =========================================================================
    # 💡 [수정됨] 중복 선언 버그 수정 및 별표 타겟 키워드 확대
    # =========================================================================
    db_data = {"언론보도": [], "기고": []}
    news_idx = 1
    opinion_idx = 1
    
    # 교수님 이름 + 언론보도 제목에 대놓고 등장할 핵심 단어(학과명) 추가
    star_keywords = [
        "강은호", "장원준", "송문원", "이대규", "유준수", "전광호", "홍성민", 
        "첨단방위산업학과", "방위산업학과"
    ]
    # =========================================================================
    
    print(f" 총 {len(unique_items)}개의 뉴스 발견. 데이터 필터링 및 다운로드 중...")

    # 엑셀에 들어간 기사 제목들을 기억해둘 수첩
    saved_titles = [] 
    
    for item in unique_items:
        pub_date = item.get("pubDate", "")

        # 1. 2026년 기사만 필터링
        if " 2026 " not in pub_date:
            continue

        title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")

        # 2. 블랙리스트 필터링 적용
        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "선대위", "공천", "출사", "재보궐", "김어준", "안도걸", "경북", "경남", "대진대","폴리텍", "부산"]
        if any(bad_word in title or bad_word in description for bad_word in bad_keywords):
            continue

        # =================================================================
        # 3. 제목 유사도 80% 이상 중복 기사 컷
        # =================================================================
        is_duplicate = False
        for prev_title in saved_titles:
            similarity = difflib.SequenceMatcher(None, title, prev_title).ratio()
            if similarity >= 0.8:
                is_duplicate = True
                break
                
        if is_duplicate:
            continue # 비슷한 기사면 가차 없이 버림
            
        saved_titles.append(title)
        # =================================================================

        # =================================================================
        # 4. [최종 수정됨] 확장된 타겟 키워드로 별표(**) 달기
        # =================================================================
        for keyword in star_keywords:
            if keyword in title:
                title = f"** {title}"
                break 
        # =================================================================

        target_link = item.get("link", "")

        # 분류 규칙
        is_opinion = any(
            word in title for word in ["칼럼", "기고", "시론", "포럼", "특별기고"]
        )

        # 이미지 수집 및 데이터 축적
        if is_opinion:
            file_name = f"opinion_{opinion_idx:03d}.jpg" # 파일명 덮어쓰기 방지
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 

            db_data["기고"].append(
                {
                    "번호": opinion_idx,
                    "제목": title,
                    "링크": target_link,
                    "작성일": pub_date,
                    "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음",
                }
            )
            opinion_idx += 1
        else:
            file_name = f"news_{news_idx:03d}.jpg" # 파일명 덮어쓰기 방지
            img_url = extract_og_image(target_link)
            download_image(img_url, file_name) 

            db_data["언론보도"].append(
                {
                    "번호": news_idx,
                    "제목": title,
                    "링크": target_link,
                    "작성일": pub_date,
                    "이미지보기": f'=HYPERLINK("{img_url}", IMAGE("{img_url}"))' if img_url else "이미지 없음",
                }
            )
            news_idx += 1

    # =========================================================================
    # 별표 우선 정렬 및 번호 예쁘게 매기기
    # =========================================================================
    for sheet_name in ["언론보도", "기고"]:
        db_data[sheet_name].sort(key=lambda x: not x["제목"].startswith("**"))
        for idx, row in enumerate(db_data[sheet_name], start=1):
            row["번호"] = idx

    # =========================================================================
    # 구글 스프레드시트 데이터 전송 로직
    # =========================================================================
    GOOGLE_CREDENTIALS = os.environ.get("GOOGLE_CREDENTIALS")

    if GOOGLE_CREDENTIALS and (db_data["언론보도"] or db_data["기고"]):
        try:
            print("\n🚀 구글 스프레드시트 업데이트 시작...")
            creds = json.loads(GOOGLE_CREDENTIALS)
            gc = gspread.service_account_from_dict(creds)
            
            sh = gc.open("언론보도_기고칼럼_db")
            
            # 1. 언론보도 시트 전송
            ws_news = sh.worksheet("언론보도")
            ws_news.clear()
            df_news = pd.DataFrame(db_data["언론보도"])
            if not df_news.empty:
                ws_news.update(
                    range_name="A1", 
                    values=[df_news.columns.values.tolist()] + df_news.astype(str).values.tolist(),
                    value_input_option="USER_ENTERED"  
                )
                
            # 2. 기고 시트 전송
            ws_opinion = sh.worksheet("기고")
            ws_opinion.clear()
            df_opinion = pd.DataFrame(db_data["기고"])
            if not df_opinion.empty:
                ws_opinion.update(
                    range_name="A1", 
                    values=[df_opinion.columns.values.tolist()] + df_opinion.astype(str).values.tolist(),
                    value_input_option="USER_ENTERED"  
                )
            
            print("✔ 구글 스프레드시트 실시간 동기화 완료!")
        except Exception as e:
            print(f"❌ 구글 시트 동기화 실패: {e}")
            
    # 로컬 백업용 엑셀 저장소 유지
    if db_data["언론보도"] or db_data["기고"]:
        with pd.ExcelWriter("언론보도_기고칼럼_db.xlsx", engine="openpyxl") as writer:
            if not pd.DataFrame(db_data["언론보도"]).empty:
                pd.DataFrame(db_data["언론보도"]).to_excel(writer, sheet_name="언론보도", index=False)
            if not pd.DataFrame(db_data["기고"]).empty:
                pd.DataFrame(db_data["기고"]).to_excel(writer, sheet_name="기고", index=False)

if __name__ == "__main__":
    main()
