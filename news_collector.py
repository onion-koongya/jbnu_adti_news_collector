import os
import urllib.parse
import requests
from bs4 import BeautifulSoup
import pandas as pd

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
    # 2026년 최신 기사 수집을 위해 display 개수를 넉넉히 설정 (최대 100)
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
    # 파이썬 봇 차단을 막기 위한 강력한 브라우저 위장 헤더
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
    # [적용 완료] 교수님 키워드 7명
    keywords = [
        "강은호 전북대", "장원준 전북대", "송문원 전북대", 
        "이대규 전북대", "유준수 전북대", "전광호 전북대", "홍성민 전북대"
    ]
    all_items = []

    print("⚡ 네이버 뉴스 검색 시작...")
    for kw in keywords:
        all_items.extend(search_naver_news(kw))

    # 중복 기사 제거 (링크 기준)
    seen_links = set()
    unique_items = []
    for item in all_items:
        if item["link"] not in seen_links:
            seen_links.add(item["link"])
            unique_items.append(item)

    db_data = {"언론보도": [], "기고": []}
    news_idx = 1
    opinion_idx = 1

    print(f" 총 {len(unique_items)}개의 뉴스 발견. 데이터 필터링 및 다운로드 중...")

    for item in unique_items:
        pub_date = item.get("pubDate", "")

        # 1. 2026년 기사만 필터링
        if " 2026 " not in pub_date:
            continue

        # [에러 수정 완료] description 추출 및 HTML 태그 제거
        title = item.get("title", "").replace("<b>", "").replace("</b>", "")
        description = item.get("description", "").replace("<b>", "").replace("</b>", "")

        # 2. 블랙리스트 필터링 적용
        bad_keywords = ["이원택", "추미애", "정치", "선거", "이돈승", "선대위", "공천", "출사", "재보궐"]
        
        # 제목이나 요약문(description)에 블랙리스트 키워드가 하나라도 있으면 건너뜀
        if any(bad_word in title or bad_word in description for bad_word in bad_keywords):
            continue

        # 네이버 인포탈 링크(link) 최우선 사용
        target_link = item.get("link", "")

        # 3. 언론보도 vs 기고 분류 규칙
        is_opinion = any(
            word in title for word in ["칼럼", "기고", "시론", "포럼", "특별기고"]
        )

        # 4. 다운로드 및 데이터 적재
        if is_opinion:
            file_name = f"{opinion_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            success = download_image(img_url, file_name)

            db_data["기고"].append(
                {
                    "번호": opinion_idx,
                    "제목": title,
                    "링크": target_link,
                    "작성일": pub_date,
                    "이미지저장": file_name if success else "실패",
                }
            )
            opinion_idx += 1
        else:
            file_name = f"{news_idx:03d}.jpg"
            img_url = extract_og_image(target_link)
            success = download_image(img_url, file_name)

            db_data["언론보도"].append(
                {
                    "번호": news_idx,
                    "제목": title,
                    "링크": target_link,
                    "작성일": pub_date,
                    "이미지저장": file_name if success else "실패",
                }
            )
            news_idx += 1

    # 로컬 엑셀 파일(DB)로 저장 (openpyxl 엔진 명시)
    # 데이터가 비어있을 경우 발생하는 에러를 막기 위한 분기 처리
    if db_data["언론보도"] or db_data["기고"]:
        with pd.ExcelWriter("언론보도_기고칼럼_db.xlsx", engine="openpyxl") as writer:
            if db_data["언론보도"]:
                pd.DataFrame(db_data["언론보도"]).to_excel(writer, sheet_name="언론보도", index=False)
            else:
                pd.DataFrame(columns=["번호", "제목", "링크", "작성일", "이미지저장"]).to_excel(writer, sheet_name="언론보도", index=False)
                
            if db_data["기고"]:
                pd.DataFrame(db_data["기고"]).to_excel(writer, sheet_name="기고", index=False)
            else:
                pd.DataFrame(columns=["번호", "제목", "링크", "작성일", "이미지저장"]).to_excel(writer, sheet_name="기고", index=False)
        
        print("\n==============================================")
        print(" 프로세스 완료!")
        print(f"- 수집된 2026년 언론보도: {news_idx - 1}건")
        print(f"- 수집된 2026년 기고칼럼: {opinion_idx - 1}건")
        print(f"- 이미지 저장 폴더: ./{IMAGE_DIR}/")
        print("- DB 업데이트 결과: ./언론보도_기고칼럼_db.xlsx")
        print("==============================================")
    else:
        print("\n 조건에 맞는 2026년 기사가 없습니다.")


if __name__ == "__main__":
    main()
