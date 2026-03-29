"""
init_history.py — posted_history.json 초기화 스크립트
────────────────────────────────────────────────────
실행하면 Blogger에 올라간 포스트 전체를 긁어서
posted_history.json을 생성해줘요.

이후 main.py 실행 시 중복 주제를 자동으로 피해요.

사용법:
  BLOGGER_BLOG_ID=... GOOGLE_CREDENTIALS_JSON=... python init_history.py
"""

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]
HISTORY_FILE       = Path("posted_history.json")

# 툴명 키워드 — 제목에서 툴을 자동 추출할 때 사용
TOOL_KEYWORDS = [
    "Claude Code", "Cowork", "Google Stitch", "Gemini", "AI Studio",
    "Antigravity", "Firebase", "Genkit", "Veo", "Sora", "ChatGPT",
    "Perplexity", "Cursor", "Windsurf", "Bolt", "Replit", "Lovable",
    "Claude", "OpenAI", "GitHub Copilot", "Devin", "v0", "NotebookLM",
]

# 트랙 키워드 — 제목으로 트랙 추측
NEWS_KEYWORDS = ["뉴스", "브리핑", "소식", "업데이트", "출시", "발표"]
TOOL_KEYWORDS_TRACK = ["사용법", "가이드", "튜토리얼", "설정", "활용법", "마스터"]


def guess_track(title: str) -> str:
    for kw in NEWS_KEYWORDS:
        if kw in title:
            return "news"
    for kw in TOOL_KEYWORDS_TRACK:
        if kw in title:
            return "tool"
    return "edu"


def extract_tool(title: str) -> str:
    for tool in TOOL_KEYWORDS:
        if tool.lower() in title.lower():
            return tool
    return ""


def get_blogger_service():
    creds_info = json.loads(GOOGLE_CREDENTIALS)
    creds = Credentials(
        token=creds_info["token"],
        refresh_token=creds_info["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=creds_info["client_id"],
        client_secret=creds_info["client_secret"],
    )
    return build("blogger", "v3", credentials=creds)


def fetch_all_posts(service) -> list[dict]:
    """Blogger API 페이지네이션으로 전체 포스트 수집."""
    posts = []
    page_token = None

    print("📡 Blogger 포스트 전체 수집 중...")
    while True:
        kwargs = dict(
            blogId=BLOGGER_BLOG_ID,
            maxResults=50,
            fields="nextPageToken,items(title,published)",
            fetchBodies=False,
            status="live",
        )
        if page_token:
            kwargs["pageToken"] = page_token

        result = service.posts().list(**kwargs).execute()
        items = result.get("items", [])
        posts.extend(items)
        print(f"  → {len(posts)}개 수집됨...")

        page_token = result.get("nextPageToken")
        if not page_token:
            break
        time.sleep(1)  # API 레이트 리밋 방지

    print(f"✅ 총 {len(posts)}개 포스트 수집 완료")
    return posts


def build_history(posts: list[dict]) -> dict:
    """포스트 목록을 posted_history.json 형식으로 변환."""
    history_posts = []

    for post in posts:
        title = post.get("title", "")
        published = post.get("published", "")

        # 날짜 파싱 (Blogger: 2026-03-29T09:00:00+09:00)
        try:
            dt = datetime.fromisoformat(published)
            date_str = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            date_str = published[:16] if published else "unknown"

        tool  = extract_tool(title)
        track = guess_track(title)

        history_posts.append({
            "date":  date_str,
            "title": title,
            "topic": title,   # 초기화 시엔 제목을 주제로 사용
            "tool":  tool,
            "track": track,
        })

    # 날짜 오름차순 정렬
    history_posts.sort(key=lambda x: x["date"])
    return {"posts": history_posts}


def main():
    print("=" * 55)
    print("🔧 posted_history.json 초기화 스크립트")
    print("=" * 55)

    # 기존 파일 백업
    if HISTORY_FILE.exists():
        backup = Path("posted_history.backup.json")
        backup.write_text(HISTORY_FILE.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"📦 기존 파일 백업 완료 → {backup}")

    service = get_blogger_service()
    posts   = fetch_all_posts(service)
    history = build_history(posts)

    HISTORY_FILE.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print()
    print("=" * 55)
    print(f"✅ posted_history.json 생성 완료!")
    print(f"   총 {len(history['posts'])}개 포스트 기록됨")
    print()
    print("📋 최근 10개 포스트:")
    for p in history["posts"][-10:]:
        print(f"  [{p['track']:4s}] {p['date']} | {p['tool'] or '?':15s} | {p['title'][:40]}")
    print()
    print("이제 main.py를 실행하면 중복 주제를 자동으로 피해요.")
    print("=" * 55)


if __name__ == "__main__":
    main()
