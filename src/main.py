"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v6.6.0
──────────────────────────────────────────────────────────
v6.6.0 수정사항:
  - [버그 수정] get_blocked_tools() UPDATE_KEYWORDS 예외 로직 제거
    → 업데이트/출시 소식이어도 차단 이력에 항상 포함
    → "어제 출시 소식 다뤘으면 오늘도 같은 툴 출시 소식 올라와도 차단"
    → AI 판단 단계에서 예외 허용 여부를 결정 (이력 자체는 항상 남김)
  - [버그 수정] news 트랙 add_to_history() tool 필드 누락 방지
    → todays_pick_tool 없으면 news_list 첫 번째 툴로 fallback
v6.5.0 수정사항:
  - [업데이트 예외] get_blocked_tools() 개선 (→ v6.6.0에서 롤백)
  - [각도 차단] get_blocked_angles() 추가
v6.4.0 수정사항:
  - [날짜 기반 차단] get_blocked_tools() 추가
v6.3.0 수정사항:
  - [영구 차단] PERMANENT_BLOCK 상단 고정
"""

import os
import re
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

import anthropic
import requests
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

ANTHROPIC_API_KEY  = os.environ["ANTHROPIC_API_KEY"]
GEMINI_API_KEY     = os.environ["GEMINI_API_KEY"]
BLOGGER_BLOG_ID    = os.environ["BLOGGER_BLOG_ID"]
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

# v6.7.1: workflow_dispatch의 dry_run 입력 처리.
# true 면 Blogger는 isDraft=True (URL 비공개), 인스타/유튜브/Threads 전체 스킵.
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# v6.7.2: src/posted_history.json 으로 경로 고정.
# 기존 Path("posted_history.json")은 CWD 의존 → 워크플로 commit 경로(src/)와 불일치 →
# 매 실행마다 히스토리 0개로 시작하는 잠재 버그가 있었음.
HISTORY_FILE = Path(__file__).parent / "posted_history.json"

# ═════════════════════════════════════════════════════════════════════════════
# ⛔ 영구 차단 키워드
# ═════════════════════════════════════════════════════════════════════════════
PERMANENT_BLOCK: list[str] = [
    "Sora", "소라",
]

# ═════════════════════════════════════════════════════════════════════════════
# 날짜 기반 차단 설정
# ═════════════════════════════════════════════════════════════════════════════
TOOL_BLOCK_DAYS  = 5
ANGLE_BLOCK_DAYS = 30

# ⚠️ v6.6.0: UPDATE_KEYWORDS는 프롬프트에서 AI 판단용으로만 사용
# 이력 차단 로직에서는 제거됨 (중복 방지 우선)
UPDATE_KEYWORDS: list[str] = [
    "업데이트", "출시", "새로운", "신규", "버전", "발표", "릴리즈", "개편",
    "v2", "v3", "v4", "2.0", "3.0", "4.0", "Pro", "Plus",
    "launch", "release", "update", "new", "feature", "announce",
]

ANGLE_KEYWORDS: list[str] = [
    "활용법", "사용법", "설정", "가이드", "튜토리얼", "설치",
    "입문", "기초", "시작", "연동", "자동화", "워크플로우",
    "비교", "vs", "차이", "대안", "대체",
]


def _block_clause() -> str:
    if not PERMANENT_BLOCK:
        return ""
    kw = ", ".join(PERMANENT_BLOCK)
    return f"""
## 🚫 영구 차단 키워드 (제목·본문·검색 모두 해당)
차단 목록: {kw}
- 위 키워드가 핵심 주제인 글은 절대 작성 금지
- 위 키워드를 본문의 주요 내용으로 다루는 것도 금지
- 비교 대상·각주·1줄 언급 수준은 허용하나 메인 주제 불가
"""


# ═════════════════════════════════════════════════════════════════════════════
# 날짜 기반 툴/각도 차단
# ═════════════════════════════════════════════════════════════════════════════
def get_blocked_tools(history: dict) -> dict[str, str]:
    """
    최근 TOOL_BLOCK_DAYS일 내 다룬 툴 반환.

    ✅ v6.6.0 변경: 업데이트/출시 소식이어도 차단 이력에 항상 포함.
    → "어제 출시 소식 다뤘으면 오늘 같은 툴 또 올려도 차단"
    → AI 판단 단계에서만 '새 소식이면 예외' 허용. 이력 자체는 항상 남김.
    → 이전 UPDATE_KEYWORDS 예외 로직이 연속 중복 포스팅의 원인이었음.

    반환값: {툴명(소문자): "마지막 포스팅 날짜 문자열"}
    """
    cutoff = datetime.now() - timedelta(days=TOOL_BLOCK_DAYS)
    blocked: dict[str, str] = {}

    for p in history["posts"]:
        post_date = datetime.strptime(p["date"], "%Y-%m-%d %H:%M")
        if post_date <= cutoff:
            continue

        tool = (p.get("tool") or "").strip()
        if not tool:
            continue

        key = tool.lower()
        if key not in blocked or p["date"] > blocked[key]:
            blocked[key] = p["date"]

    return blocked


def get_blocked_angles(history: dict) -> list[dict]:
    cutoff = datetime.now() - timedelta(days=ANGLE_BLOCK_DAYS)
    blocked = []
    for p in history["posts"]:
        post_date = datetime.strptime(p["date"], "%Y-%m-%d %H:%M")
        if post_date <= cutoff:
            continue
        tool  = (p.get("tool") or "").strip()
        title = p.get("title", "")
        for angle in ANGLE_KEYWORDS:
            if angle.lower() in title.lower():
                blocked.append({
                    "tool": tool,
                    "angle": angle,
                    "date": p["date"],
                    "title": title,
                })
    return blocked


def get_today_tools(history: dict) -> set[str]:
    """v6.7.1: 오늘 이미 다룬 툴 집합. 같은 날 중복 발행 절대 차단용."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    return {
        (p.get("tool") or "").strip().lower()
        for p in history["posts"]
        if p["date"].startswith(today_str) and (p.get("tool") or "").strip()
    }


def get_today_blogger_titles(blogger_posts: list[dict]) -> list[str]:
    """v6.7.2: 오늘 Blogger에 발행된 글 제목 목록.
    히스토리 파일이 비어있어도 이게 진실 소스 역할."""
    today_str = datetime.now().strftime("%Y-%m-%d")
    return [
        p["title"] for p in blogger_posts
        if p.get("published", "").startswith(today_str)
    ]


def build_date_block_section(history: dict, blogger_posts: list[dict] = None) -> str:
    lines = ["## 🔒 날짜 기반 자동 차단 (코드 직접 계산 — AI 임의 해제 불가)\n"]

    # v6.7.1: 같은 날 같은 도구 절대 차단 (Claude 재량 제거)
    today_tools = get_today_tools(history)
    if today_tools:
        lines.append("### 🚫 오늘 이미 발행한 툴 (히스토리 기준) — 절대 금지 (예외 0)")
        for t in sorted(today_tools):
            lines.append(f"  - {t}")
        lines.append("  ※ 같은 날 같은 도구를 다른 각도로도 절대 다루지 말 것")
        lines.append("  ※ '새로운 발표/연동/업데이트'라는 이유로도 예외 불가")
        lines.append("  ※ 위 도구 중 하나라도 후보라면 즉시 다른 도구로 변경\n")

    # v6.7.2: 히스토리 파일이 비었어도 Blogger API가 진실 소스. 오늘 발행된 글 제목으로 절대 차단.
    today_blogger_titles = get_today_blogger_titles(blogger_posts or [])
    if today_blogger_titles:
        lines.append("### 🚫 오늘 Blogger에 이미 발행된 글 — 동일 도구·주제 절대 금지 (예외 0)")
        for t in today_blogger_titles:
            lines.append(f'  - "{t}"')
        lines.append("  ※ 위 제목에 등장하는 모든 도구·주제는 오늘 다시 다루지 말 것")
        lines.append("  ※ '다른 각도', '새 업데이트', '다른 연동' 어떤 이유로도 예외 불가")
        lines.append("  ※ 후보가 위 제목 어디에든 등장하면 즉시 다른 도구·주제로 변경\n")

    blocked_tools = get_blocked_tools(history)
    if blocked_tools:
        lines.append(
            f"### 최근 {TOOL_BLOCK_DAYS}일 내 다룬 툴 — 선택 금지"
        )
        for tool, last_date in sorted(blocked_tools.items()):
            days_ago = (datetime.now() - datetime.strptime(last_date, "%Y-%m-%d %H:%M")).days
            lines.append(f"  - {tool} (마지막: {last_date}, {days_ago}일 전)")
        lines.append("")
        lines.append("  ※ 단, 어제 이전(24시간 경과)이고 해당 툴의 완전히 새로운 기능 발표 /")
        lines.append("     major 버전 출시 / 서비스 종료 / 가격 정책 대규모 변경 등")
        lines.append("     어제와 다른 새 소식이면 허용 (오늘 이미 다룬 툴은 위 절대 금지 우선)")
        lines.append("  ※ '출시 소식'이라도 어제와 동일한 소식이면 차단 유지")
        lines.append("  ※ 예외 사용 시 reason 필드에 반드시 구체적 사유 명시\n")
    else:
        lines.append(f"  (최근 {TOOL_BLOCK_DAYS}일 내 차단된 툴 없음)\n")

    blocked_angles = get_blocked_angles(history)
    if blocked_angles:
        lines.append(
            f"### 최근 {ANGLE_BLOCK_DAYS}일 내 같은 툴+각도 조합 — 동일 각도 반복 금지"
        )
        seen = set()
        for item in blocked_angles:
            key = f"{item['tool']}_{item['angle']}"
            if key not in seen:
                seen.add(key)
                lines.append(f"  - [{item['tool']}] '{item['angle']}' 각도 ({item['date']})")
        lines.append("")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# 공통 유틸
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def clean_markdown(html: str) -> str:
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'^#{1,6}\s+(.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    return html


def search(query: str, max_tokens: int = 8000) -> str:
    today  = datetime.now().strftime("%Y년 %m월 %d일")
    cutoff = (datetime.now() - timedelta(days=2)).strftime("%Y년 %m월 %d일")
    block_clause = _block_clause()

    for attempt in range(3):
        try:
            time.sleep(15)
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                tools=[{"type": "web_search_20250305", "name": "web_search"}],
                tool_choice={"type": "auto"},
                messages=[{
                    "role": "user",
                    "content": (
                        f"오늘({today}) 기준 최근 24~48시간 이내 '{query}' 관련 최신 소식을 검색해줘.\n"
                        f"⚠️ {cutoff} 이전 기사는 제외.\n"
                        f"각 소식마다 발행일을 반드시 명시해줘. 발행일 불명확한 소식은 포함 금지.\n"
                        f"{block_clause}"
                        f"핵심 내용을 한국어로 요약해줘."
                    ),
                }],
            )
            return extract_text(response)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 검색 실패 '{query}' (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    return ""


def call_claude(prompt: str, max_tokens: int = 8000) -> dict:
    for attempt in range(3):
        try:
            time.sleep(15)
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            if "```" in raw:
                for part in raw.split("```"):
                    part = part.strip().lstrip("json").strip()
                    if part.startswith("{"):
                        raw = part
                        break
            return json.loads(raw.strip())
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def call_claude_raw(prompt: str, max_tokens: int = 8000) -> str:
    for attempt in range(3):
        try:
            time.sleep(15)
            response = claude.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text.strip()
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ Claude 호출 실패 (시도 {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def get_track() -> tuple:
    now = datetime.now()
    if now.hour < 12:
        return "news", None
    if now.timetuple().tm_yday % 2 == 0:
        return "tool", None
    return "edu", None


# ═════════════════════════════════════════════════════════════════════════════
# 히스토리 관리
# ═════════════════════════════════════════════════════════════════════════════
def load_history() -> dict:
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"posts": []}


def save_history(history: dict):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_to_history(history: dict, title: str, topic: str, tool: str, track: str):
    """
    ✅ v6.6.0: tool 필드 누락 방지 로직 추가
    - tool이 빈 문자열이면 이력에서 차단 판단이 안 됨
    - 호출부에서 이미 fallback 처리하지만 여기서도 경고 로그
    """
    if not tool:
        log.warning("  ⚠️ add_to_history: tool 필드가 비어있음 → 차단 이력 미적용 주의")

    history["posts"].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": title,
        "topic": topic,
        "tool": tool,
        "track": track,
    })
    cutoff = datetime.now() - timedelta(days=90)
    history["posts"] = [
        p for p in history["posts"]
        if datetime.strptime(p["date"], "%Y-%m-%d %H:%M") > cutoff
    ]
    save_history(history)


def get_blogger_recent_posts(max_results: int = 20) -> list[dict]:
    """v6.7: 제목 + URL + 게시일 함께 반환 (내부 링크 섹션용)."""
    try:
        creds_info = json.loads(GOOGLE_CREDENTIALS)
        creds = Credentials(
            token=creds_info["token"],
            refresh_token=creds_info["refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=creds_info["client_id"],
            client_secret=creds_info["client_secret"],
        )
        service = build("blogger", "v3", credentials=creds)
        result = service.posts().list(
            blogId=BLOGGER_BLOG_ID,
            maxResults=max_results,
            fields="items(title,url,published)",
            fetchBodies=False,
        ).execute()
        items = result.get("items", [])
        posts = [
            {"title": it["title"], "url": it.get("url", ""), "published": it.get("published", "")}
            for it in items
        ]
        log.info(f"  📋 최근 Blogger 포스트 {len(posts)}개 (제목+URL) 수집 완료")
        return posts
    except Exception as e:
        log.warning(f"  ⚠️ Blogger 최근 포스트 수집 실패: {e}")
        return []


def build_avoid_context(history: dict, blogger_posts: list[dict]) -> str:
    lines = []

    lines.append(build_date_block_section(history, blogger_posts))

    if PERMANENT_BLOCK:
        kw = ", ".join(PERMANENT_BLOCK)
        lines.append(f"""
## 🚫 영구 차단 키워드
차단 목록: {kw}
- 위 키워드가 핵심 주제인 글 절대 금지
- 제목이 달라도 내용의 주요 주제로 다루는 것 금지
""")

    cutoff_14 = datetime.now() - timedelta(days=14)
    recent_14 = [
        p for p in history["posts"]
        if datetime.strptime(p["date"], "%Y-%m-%d %H:%M") > cutoff_14
    ]
    if recent_14:
        lines.append("## 최근 14일 포스트 상세 (제목·주제·각도 유사 금지)")
        for p in recent_14:
            lines.append(
                f"- [{p['track']}] {p['date']} | {p.get('tool','?')} | {p['title']}"
            )

    if blogger_posts:
        lines.append("\n## 블로그 기존 포스트 제목 전체 (유사 각도·주제 금지)")
        for p in blogger_posts:
            lines.append(f"- {p['title']}")

    lines.append("""
## ⛔ 중복 판단 기준
- 같은 툴을 5일 이내 다시 다루는 경우
  → '출시/업데이트' 소식이어도, 어제와 동일한 소식이면 차단 유지
  → 완전히 새로운 기능/버전/정책 변경이어야 예외 허용
- 같은 툴의 활용법/설정/사용법 등 각도만 바꾼 경우 (30일 이내)
- 같은 뉴스 이벤트를 다른 제목으로 반복하는 경우
→ 위 기준 해당 시 반드시 다른 툴 / 완전히 다른 주제 선택""")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 오늘의 주제 결정
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, avoid_context: str, tool_name: str = None,
                 blogger_posts: list[dict] = None) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")
    block_clause = _block_clause()

    avoid_block = f"""
## ⛔ 아래 내용은 반드시 준수 (AI 임의 해제 불가)
{avoid_context}
{block_clause}

## ✅ 차단 예외 원칙 (매우 엄격하게 적용)
- 차단된 툴이라도 오늘 완전히 새로운 기능 / major 버전 출시 / 서비스 정책 대규모 변경이 있으면 허용
- ⚠️ 단, '출시 소식'이라는 이유만으로 예외 적용 금지
  → 어제도 같은 툴의 출시 소식을 다뤘다면 오늘도 차단
  → 어제와 다른 새로운 내용(다른 기능, 다른 버전)이어야만 예외
- 예외 사용 시 reason 필드에 "어제와 다른 점"을 구체적으로 명시
"""

    if track == "news":
        trend1 = search("Claude Code Anthropic Cowork update release 2026 latest 24h")
        trend2 = search("Google Stitch Gemini 2.5 AI Studio Veo update 2026 latest")
        trend3 = search("Antigravity Firebase Genkit AI app builder 2026 latest")
        trend4 = search("OpenAI ChatGPT model update pricing 2026 latest 24h")
        trend5 = search("Perplexity AI coding tool new feature trending 2026 today")
        context = (
            f"[Claude/Anthropic/Cowork]\n{trend1}\n\n"
            f"[Google Stitch/Gemini/AI Studio/Veo]\n{trend2}\n\n"
            f"[Antigravity/Firebase/Genkit]\n{trend3}\n\n"
            f"[OpenAI/ChatGPT]\n{trend4}\n\n"
            f"[Perplexity/기타 AI 툴]\n{trend5}"
        )

        prompt = f"""
오늘({today}) 최근 24~48시간 AI 코딩/AI 툴 업계 최신 소식입니다:
{context}

{avoid_block}

위 정보를 바탕으로 오늘의 뉴스 포스트를 구성해줘.

## 뉴스 선정 원칙
- 반드시 최근 24~48시간 이내 소식 우선
- 오래된 일반 설명 기사 제외
- 실제 업데이트/출시/정책변경/가격변경 등 구체적 뉴스
- ⚠️ 차단된 툴은 어제와 완전히 다른 새 소식이 있을 때만 선택 가능

## 도구 우선순위
최우선: Claude Code, Cowork, Google Stitch, Gemini 2.5, Antigravity, Firebase Genkit, Veo
보통: ChatGPT, Perplexity, GitHub Copilot, Devin, v0, NotebookLM
하위 (major 업데이트 있을 때만): Cursor, Windsurf, Bolt, Replit, Lovable

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 뉴스 포스트 주제 (한 문장)",
  "news_list": [
    {{"title": "뉴스1 제목", "summary": "한 줄 요약", "tool": "관련 도구명"}},
    {{"title": "뉴스2 제목", "summary": "한 줄 요약", "tool": "관련 도구명"}},
    {{"title": "뉴스3 제목", "summary": "한 줄 요약", "tool": "관련 도구명"}},
    {{"title": "뉴스4 제목", "summary": "한 줄 요약", "tool": "관련 도구명"}}
  ],
  "todays_pick": "오늘의 픽 뉴스 제목",
  "todays_pick_tool": "오늘의 픽 도구명",
  "todays_pick_reason": "픽으로 선정한 이유",
  "reason": "전체 주제 선택 이유 + 차단 툴 우회 여부 및 사유 (어제와 다른 점 명시)",
  "search_queries": ["픽 심화 검색 쿼리1", "픽 심화 검색 쿼리2", "픽 실전 사용법 쿼리"]
}}
"""

    elif track == "tool":
        trend1 = search("Claude Code Cowork Google Stitch new feature update 2026 latest")
        trend2 = search("Antigravity Firebase Genkit Gemini AI Studio update 2026 latest")
        trend3 = search("AI coding design tool trending viral 2026 today")

        prompt = f"""
오늘({today}) AI 툴 최신 트렌드입니다:
[Claude/Cowork/Stitch]
{trend1}
[Antigravity/Firebase/Gemini]
{trend2}
[전체 트렌드]
{trend3}

{avoid_block}

오늘 다룰 AI 도구를 선택하고 포스트 주제를 결정해줘.

## 도구 우선순위
최우선: Claude Code, Cowork, Google Stitch, Gemini 2.5 Pro, Google AI Studio,
        Antigravity, Firebase Genkit, Veo, Perplexity
하위 (major 업데이트 있을 때만): Cursor, Windsurf, Bolt, Replit, Lovable

## 선택 기준
- 차단 목록에 없는 툴 중 가장 최신 소식이 있는 것 우선
- 차단된 툴이라도 어제와 완전히 다른 새 소식 있으면 선택 가능
- 새 소식 없는 차단 툴은 절대 선택 금지

JSON만 출력:
{{
  "topic": "오늘의 툴 주제 (한 문장)",
  "tool": "선택한 AI 도구 이름",
  "reason": "이 도구와 주제를 선택한 이유 + 차단 툴 우회 여부 및 사유",
  "search_queries": ["심화 검색 쿼리1", "심화 검색 쿼리2", "실전 사용법 쿼리"]
}}
"""

    else:  # edu
        trend1 = search("Claude Code Cowork Google Stitch tutorial guide 2026")
        trend2 = search("AI 자동화 실전 워크플로우 툴 조합 2026 최신")
        trend3 = search("AI coding tool workflow automation tutorial 2026 trending")

        prompt = f"""
오늘({today}) AI 코딩/자동화 트렌드입니다:
[튜토리얼/가이드]
{trend1}
[자동화 워크플로우]
{trend2}
[전체 트렌드]
{trend3}

{avoid_block}

오늘 교육 포스트 주제를 결정해줘.

## 주제 유형
- 요즘 핫한 AI 툴 실전 자동화 가이드
- Claude Code / Cowork / Stitch 등 최신 툴 활용법
- AI 툴 조합 워크플로우
- AI로 실제 결과물 만드는 법
- 초보자가 자주 막히는 문제 + 해결법

## 금지 주제
- "vibe coding이란?", "AI 코딩이란?" 등 기초 입문
- Cursor/Windsurf/Bolt 기본 사용법
- 차단 목록 툴의 동일 각도 반복 (새 소식 없는 경우)

JSON만 출력:
{{
  "topic": "오늘의 교육 주제 (한 문장)",
  "tool": "주로 다루는 AI 도구 이름 (없으면 빈 문자열)",
  "reason": "이 주제를 선택한 이유 + 차단 툴 우회 여부 및 사유",
  "search_queries": ["심화 검색 쿼리1", "심화 검색 쿼리2", "실전 적용 쿼리"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=1200)

    # v6.7.2: 결정론 안전망 — 두 소스로 오늘 충돌 검사.
    #   (1) 히스토리 파일의 today_tools (이전부터 있던 검사)
    #   (2) 오늘 발행된 Blogger 제목 substring (히스토리 파일이 비어도 동작)
    history_for_check = load_history()
    today_tools = get_today_tools(history_for_check)
    today_titles = get_today_blogger_titles(blogger_posts or [])

    chosen_tools = []
    if topic_data.get("tool"):
        chosen_tools.append(topic_data["tool"].strip())
    if topic_data.get("todays_pick_tool"):
        chosen_tools.append(topic_data["todays_pick_tool"].strip())

    forbidden_reasons = []
    for tool in chosen_tools:
        tl = tool.lower()
        if not tl:
            continue
        if tl in today_tools:
            forbidden_reasons.append(f"{tool} (히스토리에 오늘 발행됨)")
            continue
        for title in today_titles:
            if tl in title.lower():
                forbidden_reasons.append(f'{tool} (오늘 Blogger 제목에 등장: "{title}")')
                break

    if forbidden_reasons:
        log.warning(f"  🚫 오늘 이미 다룬 도구 선택됨 → 강제 재시도: {forbidden_reasons}")
        forbidden_tool_list = ", ".join(set(chosen_tools))
        retry_prompt = (
            prompt
            + "\n\n## ⛔⛔⛔ 강제 재시도 (이전 응답 거부됨)\n"
            + f"방금 너는 {forbidden_tool_list} 를 선택했는데 이 도구는 오늘 이미 발행됐다.\n"
            + "차단 사유:\n"
            + "\n".join(f"  - {r}" for r in forbidden_reasons)
            + "\n절대 같은 도구 선택 금지. 위 도구 우선순위 목록에서 완전히 다른 도구로 즉시 변경.\n"
            + "Claude/Anthropic 계열도 완전히 다른 도구로 변경 (Claude 4.x 어떤 버전이든 차단).\n"
        )
        topic_data = call_claude(retry_prompt, max_tokens=1200)

    log.info(f"  ✅ 결정된 주제: {topic_data['topic']}")
    log.info(f"  💡 선택 이유: {topic_data.get('reason', '')}")
    return topic_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: 심화 뉴스 수집
# ═════════════════════════════════════════════════════════════════════════════
def collect_deep_news(topic_data: dict) -> str:
    log.info("📡 심화 뉴스 수집 중...")
    results = []
    for q in topic_data.get("search_queries", []):
        text = search(q)
        if text:
            results.append(f"[{q}]\n{text}")
    combined = "\n\n".join(results)
    log.info(f"  ✅ 심화 뉴스 수집 완료 ({len(combined)}자)")
    return combined


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: 블로그 글 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_post(track: str, topic_data: dict, deep_news: str) -> dict:
    log.info("✍️  블로그 글 작성 시작...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")
    topic = topic_data["topic"]
    block_clause = _block_clause()

    base_rules = f"""
블로그명: 바이브코딩 스쿨 (VIBE CODING School)
오늘 날짜: {today} ({year}년 기준으로만 작성)
오늘 주제: {topic}

## ⚠️ 연도 규칙 (최우선 적용)
- 현재 연도는 {year}년입니다. 이것은 확정된 사실입니다.
- 제목과 본문에 포함된 연도({year})를 절대 변경하지 마세요.

{block_clause}

## 바이브코딩 스쿨 글쓰기 원칙
- 독자: AI 코딩/자동화에 관심 있는 모든 사람
- 어조: 친근하고 명확하게 ("~해요", "~거예요", "~네요")
- "직장인", "주부", "소상공인" 같은 특정 직군 표현 사용 금지
- 전문용어 나오면 반드시 쉽게 풀어서 설명
- {year}년 현재 기준 (다른 연도 절대 금지)
- "vibe coding이란?", "AI 코딩이란?" 같은 기초 설명으로 글 시작 금지
- 수집된 정보를 단순 요약하지 말고 실용적인 인사이트와 의견 추가

## 사실 확인 원칙
- 수집된 정보에 명시된 수치/사실만 사용
- 없는 내용 창작/추측 금지
- 불확실한 내용은 "~라고 알려져 있어요" 완화 표현 사용

## ⚠️ 제목 숫자/키워드 규칙
- 본문에서 실제로 다루는 단계/방법/팁의 개수를 먼저 확인하고 작성
- 숫자는 본문 실제 개수와 반드시 일치

## ⚠️ 마무리 규칙
- "다음 편에서는", "다음 글에서는", "내일은" 같은 예고 문구 절대 사용 금지
- 마무리는 오늘 다룬 내용 핵심 요약으로만 끝낼 것
"""

    if track == "news":
        news_list   = topic_data.get("news_list", [])
        todays_pick = topic_data.get("todays_pick", "")
        todays_tool = topic_data.get("todays_pick_tool", "")
        news_bullets = "\n".join([
            f"- [{n.get('tool','')}] {n['title']}: {n['summary']}"
            for n in news_list
        ])
        structure = f"""
## 뉴스 트랙 글 구조

### 파트 1: 오늘의 AI 코딩 뉴스 브리핑
오늘의 주요 뉴스 {len(news_list)}개를 각각 뉴스 카드 형태로 작성.
{news_bullets}

### 파트 2: 🎯 오늘의 픽 — {todays_pick} ({todays_tool})
- 이게 뭔지 쉽게 설명 (2~3줄)
- 단계별 가이드 (정확히 5단계)
- 막히는 포인트 + 해결법 (정확히 3가지)
- 실제 활용 예시 (정확히 3가지)

### 파트 3: 마무리 (예고 문구 없이)

분량: 2500~3000자
"""

    elif track == "tool":
        tool = topic_data.get("tool", "AI 도구")
        structure = f"""
## 툴 트랙 글 구조 ({tool})

1. 공감 도입
2. {tool} 최신 업데이트 핵심 변경사항 (정확히 3가지)
3. 단계별 실전 가이드 (정확히 6단계)
4. 실제 결과물 예시 (정확히 2가지)
5. 자주 막히는 포인트 + 해결법 (정확히 3가지)
6. 마무리 (예고 문구 없이)

분량: 2500~3000자
"""

    else:
        structure = """
## 교육 트랙 글 구조

1. 공감 도입
2. 필요한 도구 + 준비물 (정확히 3가지 이내)
3. 단계별 실전 방법 (정확히 5단계)
4. 실제 활용 예시 (정확히 3가지)
5. 주의사항 + 흔한 실수 (정확히 3가지)
6. 마무리 (예고 문구 없이)

분량: 2500~3000자
"""

    log.info("  ✍️  1단계: HTML 본문 생성 중...")
    html_prompt = f"""
{base_rules}
{structure}

수집된 최신 정보:
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}

## HTML 스타일 가이드

1. 핵심 요약 박스:
<div style="background:#F3F0FF;border-left:4px solid #6366F1;border-radius:0 8px 8px 0;padding:16px 20px;margin:24px 0"><p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#4338CA">💡 핵심 포인트</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.7">내용</p></div>

2. 뉴스 카드:
<div style="background:#fff;border:1px solid #E0E7FF;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#6366F1;color:#fff;font-size:12px;font-weight:700;padding:4px 10px;border-radius:20px;flex-shrink:0;white-space:nowrap">도구명</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1E1B4B">뉴스 제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용</p></div></div>

3. 번호 카드:
<div style="background:#fff;border:1px solid #E0E7FF;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#6366F1;color:#fff;font-size:14px;font-weight:700;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0">1</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1E1B4B">단계 제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용</p></div></div>

4. 픽/팁 박스:
<div style="background:#EEF2FF;border-radius:12px;padding:16px 20px;margin:20px 0"><p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#6366F1">🎯 오늘의 픽</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.6">내용</p></div>

5. h2 제목:
<h2 style="font-size:18px;font-weight:700;color:#1E1B4B;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #6366F1">제목</h2>

6. 본문:
<p style="font-size:16px;color:#374151;line-height:1.8;margin:20px 0">내용</p>

규칙:
- 마크다운 절대 금지, 굵게는 <strong> 태그
- 완성된 HTML만 출력
"""
    content_html = call_claude_raw(html_prompt, max_tokens=5000)

    if content_html.startswith("```"):
        lines = content_html.split("\n")
        content_html = "\n".join(
            lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        )

    content_html = clean_markdown(content_html)
    log.info(f"  ✅ HTML 본문 생성 완료 ({len(content_html)}자)")

    log.info("  📋 2단계: 본문 기반 메타데이터 생성 중...")
    meta_prompt = f"""
아래 블로그 본문을 읽고 메타데이터를 생성해줘.

## ⚠️ 연도 규칙 (최우선)
- 현재 연도는 {year}년입니다. 확정된 사실입니다.
- 제목에 연도를 포함할 때 반드시 {year}년으로 작성하세요.

{block_clause}

## 블로그 본문 (HTML):
{content_html[:3000]}

## SEO 제목 규칙
- 형식: [핵심 키워드] + [구체적 방법/결과] + ({year})
- 숫자가 들어간다면 반드시 본문 실제 개수와 일치
- 클릭베이트 절대 금지

## 태그 규칙
- 총 3~5개
- 필수: Claude, 바이브코딩, AI코딩, 앱개발, AI자동화, AI에이전트, 초보자가이드 중 1~2개

## FAQ 규칙 (v6.7 추가 — Google FAQ 리치결과 노출용)
- 본문 내용 기반 자주 묻는 질문 정확히 3개
- 각 질문은 실제 검색 의도 반영 (예: "~방법", "~비용", "~차이")
- 답변은 1~2문장, 60~120자
- 본문에 명시된 사실만 사용

JSON만 출력:
{{
  "title_candidates": [
    "제목1 ({year})",
    "제목2 ({year})",
    "제목3 ({year})",
    "제목4 ({year})",
    "제목5 ({year})"
  ],
  "meta_description": "메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3"],
  "slug": "seo-english-slug-{year}",
  "faq": [
    {{"q": "질문1", "a": "답변1 (60~120자)"}},
    {{"q": "질문2", "a": "답변2 (60~120자)"}},
    {{"q": "질문3", "a": "답변3 (60~120자)"}}
  ]
}}
"""
    meta_data = call_claude(meta_prompt, max_tokens=1100)
    meta_data["content_html"] = content_html
    log.info("  ✅ 메타데이터 생성 완료")
    return meta_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: SEO 제목 선택
# ═════════════════════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
    log.info("🔍 SEO 제목 최적화...")
    year = datetime.now().year
    candidates = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(post_data["title_candidates"])
    )
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""다음 제목 후보 중 SEO에 가장 좋은 제목 1개만 출력 (번호 없이).
기준: 핵심 키워드 앞배치, 숫자가 있다면 본문 실제 내용과 일치, 클릭베이트 없음

⚠️ 중요: 연도는 반드시 {year}년 그대로 유지. 절대 수정 금지.

후보:
{candidates}""",
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4-B: 제목-내용 일치 검증
# ═════════════════════════════════════════════════════════════════════════════
def verify_title_content_match(title: str, content_html: str) -> str:
    log.info("🔎 제목-내용 일치 검증 중...")
    year = datetime.now().year

    for attempt in range(2):
        verify_prompt = f"""
아래 블로그 제목과 본문을 검토하고, 불일치가 있으면 수정된 제목을 반환해줘.

## ⚠️ 연도 규칙 (최우선)
- 현재 연도는 {year}년입니다. 확정된 사실입니다.
- 제목의 연도({year})는 절대 수정하지 마세요.

## 현재 제목
{title}

## 본문 앞부분 (HTML)
{content_html[:4000]}

## 검증 기준 (연도 제외)
1. 숫자 일치: 제목의 "N가지/N단계" 숫자와 본문 실제 항목 수 일치 여부
2. 핵심 키워드: 제목에 언급된 도구명/기능명이 본문에서 실제로 다뤄지는지
3. 과장 표현: 본문에 없는 내용을 제목이 암시하는지

## 출력 형식 (JSON, 코드블록 없이)
일치하면:
{{"status": "ok", "title": "{title}"}}

불일치이면 (연도는 반드시 {year}년 유지):
{{"status": "fixed", "title": "수정된 제목 ({year})", "reason": "수정 이유"}}
"""
        result    = call_claude(verify_prompt, max_tokens=300)
        status    = result.get("status", "ok")
        new_title = result.get("title", title).strip()

        if str(year) in title and str(year) not in new_title:
            log.warning("  ⚠️ 연도 변경 감지! 강제 복원 중...")
            for wrong_year in [year - 1, year - 2, year + 1, year - 3]:
                new_title = new_title.replace(str(wrong_year), str(year))
            log.info(f"  🔧 연도 복원 완료: {new_title}")

        if status == "ok":
            log.info("  ✅ 검증 통과")
            return new_title
        else:
            log.warning(f"  ⚠️ 불일치 감지 (시도 {attempt+1}/2): {result.get('reason', '')}")
            log.info(f"  🔧 제목 수정: {title} → {new_title}")
            title = new_title

    log.info(f"  ✅ 최종 제목 확정: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: 이미지 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    tags = ", ".join(post_data.get("tags", []))
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"블로그 썸네일용 영문 이미지 프롬프트 50단어 이내.\n"
                f"제목: {title}\n태그: {tags}\n"
                "조건: 밝고 친근한 테크 일러스트, 텍스트 없음, 16:9.\n"
                "프롬프트만 출력:"
            ),
        }],
    )
    return response.content[0].text.strip()


def generate_thumbnail(image_prompt: str) -> str:
    log.info("🎨 썸네일 생성 중...")
    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail, no text no letters, professional tech design"
    )
    try:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-image:generateContent?key={GEMINI_API_KEY}"
        )
        payload = {
            "contents": [{"parts": [{"text": enhanced}]}],
            "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
        }
        resp = requests.post(url, json=payload, timeout=90)
        resp.raise_for_status()
        for part in resp.json()["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                log.info("  ✅ 이미지 생성 완료")
                return part["inlineData"]["data"]
    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e})")
    return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: 이미지 업로드
# ═════════════════════════════════════════════════════════════════════════════
def upload_image_to_imgur(image_b64: str) -> str:
    if not image_b64:
        return ""
    try:
        log.info("☁️  이미지 imgur 업로드 중...")
        resp = requests.post(
            "https://api.imgur.com/3/image",
            headers={"Authorization": "Client-ID 546c25a59c58ad7"},
            data={"image": image_b64, "type": "base64"},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("success"):
            img_url = data["data"]["link"]
            log.info(f"  ✅ imgur 업로드 완료: {img_url}")
            return img_url
        return ""
    except Exception as e:
        log.warning(f"  ⚠️ imgur 업로드 실패 ({e})")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7: Blogger 포스팅
# ═════════════════════════════════════════════════════════════════════════════
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


# ═════════════════════════════════════════════════════════════════════════════
# v6.7 SEO 헬퍼들
# ═════════════════════════════════════════════════════════════════════════════
def build_toc_html(content_html: str) -> str:
    """본문 h2 태그를 파싱해서 목차 박스 생성. 매칭 없으면 빈 문자열."""
    import re
    h2_matches = re.findall(r'<h2[^>]*>(.*?)</h2>', content_html, re.DOTALL)
    h2_titles = [re.sub(r'<[^>]+>', '', h).strip() for h in h2_matches]
    h2_titles = [t for t in h2_titles if t]
    if len(h2_titles) < 2:
        return ""

    items = "\n".join(
        f'    <li style="margin:6px 0;color:#374151;">{t}</li>'
        for t in h2_titles
    )
    return f"""
<div style="background:#F9FAFB;border:1px solid #E5E7EB;border-radius:12px;padding:18px 22px;margin:24px 0;">
  <p style="margin:0 0 10px;font-size:13px;font-weight:700;color:#6366F1;">📑 이 글의 목차</p>
  <ol style="margin:0;padding-left:20px;font-size:14px;line-height:1.8;">
{items}
  </ol>
</div>
"""


def build_internal_links_html(blogger_posts: list[dict], current_title: str, count: int = 5) -> str:
    """본문 끝 '함께 읽으면 좋은 글' 섹션. 현재 글 제외, 최근 count개."""
    if not blogger_posts:
        return ""
    others = [p for p in blogger_posts if p.get("title") and p.get("url") and p["title"] != current_title]
    picks = others[:count]
    if not picks:
        return ""

    items = "\n".join(
        f'    <li style="margin:8px 0;"><a href="{p["url"]}" '
        f'style="color:#4338CA;text-decoration:none;font-weight:500;">→ {p["title"]}</a></li>'
        for p in picks
    )
    return f"""
<div style="background:#F3F0FF;border-left:4px solid #6366F1;border-radius:0 12px 12px 0;padding:18px 22px;margin:32px 0;">
  <p style="margin:0 0 10px;font-size:14px;font-weight:700;color:#4338CA;">📚 함께 읽으면 좋은 글</p>
  <ul style="margin:0;padding-left:18px;font-size:14px;line-height:1.7;">
{items}
  </ul>
</div>
"""


def build_cross_channel_cta_html() -> str:
    """블로그 → 유튜브/인스타/Threads 크로스채널 유입. 환경변수 누락 시 자동 생략."""
    yt   = os.environ.get("YOUTUBE_CHANNEL_URL", "")
    ig   = os.environ.get("INSTAGRAM_PROFILE_URL", "")
    th   = os.environ.get("THREADS_PROFILE_URL", "")
    links = []
    if yt:
        links.append(f'<a href="{yt}" style="color:#fff;text-decoration:none;font-weight:600;background:#FF0000;padding:8px 14px;border-radius:6px;display:inline-block;margin:4px;">▶ YouTube 쇼츠</a>')
    if ig:
        links.append(f'<a href="{ig}" style="color:#fff;text-decoration:none;font-weight:600;background:#E4405F;padding:8px 14px;border-radius:6px;display:inline-block;margin:4px;">📸 Instagram</a>')
    if th:
        links.append(f'<a href="{th}" style="color:#fff;text-decoration:none;font-weight:600;background:#000;padding:8px 14px;border-radius:6px;display:inline-block;margin:4px;">🧵 Threads</a>')
    if not links:
        return ""
    return f"""
<div style="background:#fff;border:1px solid #E5E7EB;border-radius:12px;padding:20px;margin:24px 0;text-align:center;">
  <p style="margin:0 0 12px;font-size:14px;font-weight:700;color:#1E1B4B;">📱 같은 내용을 영상·카드뉴스로도 보세요</p>
  <div>{' '.join(links)}</div>
</div>
"""


def build_faq_html_and_jsonld(faq: list[dict]) -> tuple[str, str]:
    """FAQ 섹션 HTML + FAQ Page JSON-LD (Google 리치결과용)."""
    if not faq:
        return "", ""
    items_html = []
    for i, qa in enumerate(faq):
        q = qa.get("q", "").strip()
        a = qa.get("a", "").strip()
        if not q or not a:
            continue
        items_html.append(f"""
  <details style="background:#fff;border:1px solid #E5E7EB;border-radius:8px;padding:14px 18px;margin:10px 0;">
    <summary style="font-weight:700;color:#1E1B4B;cursor:pointer;font-size:15px;">Q. {q}</summary>
    <p style="margin:10px 0 0;color:#374151;font-size:14px;line-height:1.7;">A. {a}</p>
  </details>""")
    if not items_html:
        return "", ""

    faq_html = f"""
<div style="margin:32px 0;">
  <h2 style="font-size:18px;font-weight:700;color:#1E1B4B;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #6366F1;">자주 묻는 질문</h2>
{''.join(items_html)}
</div>
"""

    valid_qa = [qa for qa in faq if qa.get("q") and qa.get("a")]
    main_entity = [
        {
            "@type": "Question",
            "name": qa["q"].strip(),
            "acceptedAnswer": {"@type": "Answer", "text": qa["a"].strip()},
        }
        for qa in valid_qa
    ]
    jsonld = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": main_entity,
    }
    return faq_html, f'<script type="application/ld+json">{json.dumps(jsonld, ensure_ascii=False)}</script>'


def build_article_jsonld(title: str, description: str, image_url: str, blog_url: str = "") -> str:
    """Article schema. blog_url 비어 있으면 url 필드 생략."""
    site_name = "바이브코딩 스쿨"
    obj = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": title,
        "description": description or title,
        "image": [image_url] if image_url else [],
        "datePublished": datetime.now().isoformat(),
        "dateModified": datetime.now().isoformat(),
        "author": {"@type": "Organization", "name": site_name},
        "publisher": {
            "@type": "Organization",
            "name": site_name,
        },
    }
    if blog_url:
        obj["mainEntityOfPage"] = {"@type": "WebPage", "@id": blog_url}
    return f'<script type="application/ld+json">{json.dumps(obj, ensure_ascii=False)}</script>'


# ═════════════════════════════════════════════════════════════════════════════
# Blogger 포스팅 (v6.7 — 내부 링크 + JSON-LD + ToC + FAQ + 크로스채널 CTA)
# ═════════════════════════════════════════════════════════════════════════════
def post_to_blogger(
    title: str,
    post_data: dict,
    image_url: str,
    blogger_posts: list[dict] = None,
    track: str = "",
) -> str:
    log.info("📤 Blogger 포스팅 중...")
    if not image_url:
        image_url = "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"

    year = datetime.now().year
    blogger_posts = blogger_posts or []

    # SEO 메타 정보
    description = post_data.get("meta_description", title)
    tags        = post_data.get("tags", [])
    faq         = post_data.get("faq", [])
    content_html = post_data["content_html"]

    # 풍부한 alt
    alt_track = {"news": "AI 코딩 뉴스", "tool": "AI 도구 가이드", "edu": "AI 코딩 교육"}.get(track, "AI 코딩 가이드")
    alt_text = f"{title} - 바이브코딩 스쿨 {alt_track} ({year}년)"

    # 섹션별 조립
    article_jsonld = build_article_jsonld(title, description, image_url)
    faq_html, faq_jsonld = build_faq_html_and_jsonld(faq)
    toc_html = build_toc_html(content_html)
    internal_links_html = build_internal_links_html(blogger_posts, current_title=title, count=5)
    cross_channel_html  = build_cross_channel_cta_html()

    full_html = f"""
{article_jsonld}
{faq_jsonld}

<div style="margin-bottom:2rem;">
  <img src="{image_url}" alt="{alt_text}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>

{toc_html}

{content_html}

{faq_html}

{cross_channel_html}

{internal_links_html}

<hr style="margin:3rem 0;border:none;border-top:1px solid #eee;" />
<div style="background:#f0f4ff;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>바이브코딩 스쿨</strong>은 코딩 없이도 AI로 앱을 만들 수 있도록
    매일 아침·저녁 최신 내용을 업데이트합니다. 구독하고 놓치지 마세요! 🔔
  </p>
</div>
"""
    service = get_blogger_service()
    result  = service.posts().insert(
        blogId=BLOGGER_BLOG_ID,
        body={
            "title": title,
            "content": full_html,
            "labels": tags,
        },
        isDraft=DRY_RUN,  # v6.7.1: dry-run이면 초안으로만 저장 (공개 URL 노출 X)
    ).execute()
    post_url = result.get("url", "URL 없음")
    if DRY_RUN:
        log.info(f"  🧪 DRY_RUN 초안 저장 완료 (공개 안 됨): {post_url}")
    else:
        log.info(f"  ✅ 포스팅 완료: {post_url}")
    return post_url


# ═════════════════════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 바이브코딩 스쿨 자동화 시작 (v6.7.1)")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"   현재 연도: {datetime.now().year}년 (고정)")
    log.info(f"   영구 차단: {', '.join(PERMANENT_BLOCK) if PERMANENT_BLOCK else '없음'}")
    if DRY_RUN:
        log.info("   🧪 DRY_RUN 모드: Blogger=초안 저장, 인스타/유튜브/Threads 전체 스킵")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 트랙: {track.upper()}")

        log.info("📋 히스토리 로드 + 날짜 기반 차단 계산 중...")
        history       = load_history()
        blogger_posts = get_blogger_recent_posts(max_results=20)

        blocked_tools = get_blocked_tools(history)
        if blocked_tools:
            log.info(
                f"  🔒 날짜 차단 툴 (최근 {TOOL_BLOCK_DAYS}일): "
                + ", ".join(f"{t}({d})" for t, d in blocked_tools.items())
            )
        else:
            log.info(f"  ✅ 날짜 차단 툴 없음")

        blocked_angles = get_blocked_angles(history)
        if blocked_angles:
            seen, summary = set(), []
            for item in blocked_angles:
                key = f"{item['tool']}_{item['angle']}"
                if key not in seen:
                    seen.add(key)
                    summary.append(f"{item['tool']}:{item['angle']}")
            log.info(f"  🔒 각도 차단 (최근 {ANGLE_BLOCK_DAYS}일): {', '.join(summary)}")

        avoid_context = build_avoid_context(history, blogger_posts)
        log.info(
            f"  ✅ 히스토리 {len(history['posts'])}개 "
            f"+ Blogger 포스트 {len(blogger_posts)}개 로드"
        )

        topic_data = decide_topic(track, avoid_context, tool_name, blogger_posts=blogger_posts)
        deep_news  = collect_deep_news(topic_data)
        post_data  = generate_post(track, topic_data, deep_news)
        best_title = select_best_title(post_data)
        best_title = verify_title_content_match(best_title, post_data["content_html"])

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)
        image_url    = upload_image_to_imgur(image_b64)

        blog_url = post_to_blogger(
            best_title, post_data, image_url,
            blogger_posts=blogger_posts,
            track=track,
        )

        # ✅ v6.6.0: tool 필드 누락 방지 — news 트랙 fallback 처리
        tool_for_history = (
            topic_data.get("tool")
            or topic_data.get("todays_pick_tool")
            or (topic_data.get("news_list") or [{}])[0].get("tool", "")
        )
        if not tool_for_history:
            log.warning("  ⚠️ tool 필드를 확정할 수 없음 — 히스토리에 tool 없이 저장됨")

        add_to_history(
            history,
            title=best_title,
            topic=topic_data["topic"],
            tool=tool_for_history,
            track=track,
        )
        log.info(f"  ✅ 히스토리 업데이트 완료 (tool: {tool_for_history or '미확정'})")

        card_image_urls = []
        if DRY_RUN:
            log.info("  🧪 DRY_RUN: 인스타/유튜브/Threads 전체 스킵")
        else:
            try:
                from instagram import post_instagram
                insta_url, card_image_urls = post_instagram(
                    blog_title=best_title,
                    blog_content_html=post_data["content_html"],
                    tags=post_data.get("tags", []),
                )
                log.info(f"  📸 인스타 포스팅 완료: {insta_url}")
            except Exception as e:
                log.warning(f"  ⚠️ 인스타 포스팅 실패: {e}")

            try:
                from youtube_shorts import post_youtube_shorts
                youtube_url = post_youtube_shorts(
                    title=best_title,
                    content_html=post_data["content_html"],
                    blog_url=blog_url,
                    card_image_urls=card_image_urls,
                )
                if youtube_url:
                    log.info(f"  🎬 유튜브 쇼츠 완료: {youtube_url}")
            except Exception as e:
                log.warning(f"  ⚠️ 유튜브 쇼츠 실패: {e}")

            try:
                from threads import post_threads
                threads_url = post_threads(
                    blog_title=best_title,
                    blog_content_html=post_data["content_html"],
                    blog_url=blog_url,
                    tags=post_data.get("tags", []),
                    track=track,
                    image_url=image_url,
                )
                if threads_url:
                    log.info(f"  🧵 Threads 포스팅 완료: {threads_url}")
            except Exception as e:
                log.warning(f"  ⚠️ Threads 포스팅 실패: {e}")

        log.info("=" * 60)
        log.info("🎉 전체 파이프라인 완료!")
        log.info(f"   트랙: {track.upper()} | 주제: {topic_data['topic']}")
        log.info(f"   제목: {best_title}")
        log.info(f"   블로그 URL: {blog_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
