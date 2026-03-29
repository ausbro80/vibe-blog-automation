"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v6.2
──────────────────────────────────────────────────────────
v6.2 수정사항:
  - [중복 방지 1] Blogger API로 최근 20개 포스트 제목 수집 → 주제 결정 시 참고
  - [중복 방지 2] posted_history.json으로 로컬 주제/툴 기록 관리
  - [제목-내용 일치 1] 본문 먼저 생성 → 본문 기반으로 제목 생성 (순서 변경)
  - [제목-내용 일치 2] verify_title_content_match() 검증 단계 추가
    → 제목의 숫자/키워드가 본문과 불일치하면 자동으로 제목 재생성
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

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# 로컬 히스토리 파일 경로
HISTORY_FILE = Path("posted_history.json")


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
    today = datetime.now().strftime("%Y년 %m월 %d일")
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
                    "content": f"오늘({today}) 기준 최근 24시간~48시간 이내 '{query}' 관련 최신 소식을 검색하고 핵심 내용을 한국어로 요약해줘. 오래된 내용보다 가장 최신 업데이트 우선.",
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
# [NEW v6.1] 중복 방지 — 히스토리 관리
# ═════════════════════════════════════════════════════════════════════════════
def load_history() -> dict:
    """로컬 posted_history.json 로드. 없으면 빈 구조 반환."""
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"posts": []}


def save_history(history: dict):
    """히스토리를 JSON 파일에 저장."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_to_history(history: dict, title: str, topic: str, tool: str, track: str):
    """새 포스트 정보를 히스토리에 추가하고 90일 이상 된 항목 정리."""
    history["posts"].append({
        "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "title": title,
        "topic": topic,
        "tool": tool,
        "track": track,
    })
    # 90일 이상 된 항목 제거
    cutoff = datetime.now() - timedelta(days=90)
    history["posts"] = [
        p for p in history["posts"]
        if datetime.strptime(p["date"], "%Y-%m-%d %H:%M") > cutoff
    ]
    save_history(history)


def get_blogger_recent_titles(max_results: int = 20) -> list[str]:
    """Blogger API로 최근 포스트 제목 N개 가져오기."""
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
            fields="items(title)",
            fetchBodies=False,
        ).execute()
        titles = [item["title"] for item in result.get("items", [])]
        log.info(f"  📋 최근 Blogger 포스트 {len(titles)}개 제목 수집 완료")
        return titles
    except Exception as e:
        log.warning(f"  ⚠️ Blogger 최근 제목 수집 실패: {e}")
        return []


def build_avoid_context(history: dict, blogger_titles: list[str]) -> str:
    """중복 방지용 '이미 다룬 내용' 컨텍스트 문자열 생성."""
    lines = []

    all_posts = history["posts"]
    if all_posts:
        # 툴별 최근 다룬 날짜 집계
        tool_map: dict[str, list[str]] = {}
        for p in all_posts:
            tool = p.get("tool") or "기타"
            tool_map.setdefault(tool, []).append(p["date"])

        lines.append("## 툴별 최근 다룬 날짜 (같은 툴은 최소 5일 이상 간격 필요)")
        for tool, dates in sorted(tool_map.items()):
            last = max(dates)
            count = len(dates)
            lines.append(f"- {tool}: 총 {count}회 다룸, 마지막 {last}")

        # 최근 14일 포스트 상세
        cutoff_14 = datetime.now() - timedelta(days=14)
        recent_14 = [
            p for p in all_posts
            if datetime.strptime(p["date"], "%Y-%m-%d %H:%M") > cutoff_14
        ]
        if recent_14:
            lines.append("\n## 최근 14일 포스트 상세 (제목·주제 유사 금지)")
            for p in recent_14:
                lines.append(
                    f"- [{p['track']}] {p['date']} | {p.get('tool','?')} | {p['title']}"
                )

    # Blogger 전체 제목
    if blogger_titles:
        lines.append("\n## 블로그 기존 포스트 제목 전체 (유사 각도·주제 금지)")
        for t in blogger_titles:
            lines.append(f"- {t}")

    lines.append("""
## ⛔ 중복 판단 기준 (제목이 달라도 아래 해당하면 중복)
- 같은 툴을 5일 이내에 다시 다루는 경우
- 같은 툴의 '활용법', '설정 가이드', '사용법' 등 각도만 바꾼 경우
- 같은 뉴스 이벤트를 다른 제목으로 반복하는 경우
→ 위 기준 해당 시 반드시 다른 툴 / 완전히 다른 주제 선택""")

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: 오늘의 주제 결정 (24시간 핫토픽 기반 + 중복 방지)
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, avoid_context: str, tool_name: str = None) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    avoid_block = f"""
## ⛔ 중복 방지 — 아래 주제/툴/제목과 겹치는 것은 절대 선택 금지
{avoid_context}
""" if avoid_context else ""

    if track == "news":
        trend1 = search("Claude Code Anthropic Cowork update release 2026 latest 24h")
        trend2 = search("Google Stitch Gemini 2.5 AI Studio Veo update 2026 latest")
        trend3 = search("Antigravity Firebase Genkit AI app builder 2026 latest")
        trend4 = search("OpenAI ChatGPT Sora model update pricing 2026 latest 24h")
        trend5 = search("Perplexity AI coding tool new feature trending 2026 today")
        context = (
            f"[Claude/Anthropic/Cowork]\n{trend1}\n\n"
            f"[Google Stitch/Gemini/AI Studio/Veo]\n{trend2}\n\n"
            f"[Antigravity/Firebase/Genkit]\n{trend3}\n\n"
            f"[OpenAI/ChatGPT/Sora]\n{trend4}\n\n"
            f"[Perplexity/기타 AI 툴]\n{trend5}"
        )

        prompt = f"""
오늘({today}) 최근 24~48시간 AI 코딩/AI 툴 업계 최신 소식입니다:
{context}

{avoid_block}

위 정보를 바탕으로 오늘의 뉴스 포스트를 구성해줘.

## 뉴스 선정 원칙
- 반드시 최근 24~48시간 이내에 발생한 소식 우선
- 오래된 일반 설명 기사 제외
- 실제 업데이트/출시/정책변경/가격변경 등 구체적 뉴스 선정
- 이미 다룬 툴/주제는 반드시 피할 것

## 도구 우선순위 (요즘 핫한 것)
최우선: Claude Code, Cowork, Google Stitch, Gemini 2.5, Antigravity, Firebase Genkit, Veo, Sora
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
  "reason": "전체 주제 선택 이유 + 중복 피한 방법",
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
이미 최근에 다룬 툴은 반드시 피할 것.

## 도구 우선순위 (요즘 진짜 핫한 것)
최우선 선택:
- Claude Code — 터미널 기반 AI 코딩 에이전트
- Cowork — Claude 기반 모바일/데스크탑 파일 자동화
- Google Stitch — AI 기반 UI 디자인 도구 (요즘 급부상)
- Gemini 2.5 Pro — 구글 최신 AI 모델
- Google AI Studio — Gemini API 실험 환경
- Antigravity — Claude 기반 앱 빌더
- Firebase Genkit — AI 앱 개발 프레임워크
- Veo / Sora — AI 영상 생성
- Perplexity — AI 검색+코딩

하위 우선순위 (major 업데이트 있을 때만):
- Cursor, Windsurf, Bolt, Replit, Lovable

JSON만 출력:
{{
  "topic": "오늘의 툴 주제 (한 문장)",
  "tool": "선택한 AI 도구 이름",
  "reason": "이 도구와 주제를 선택한 이유 + 중복 피한 방법",
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
이미 다룬 주제와 겹치지 않게 선택할 것.

## 주제 유형
- 요즘 핫한 AI 툴 실전 자동화 가이드
- Claude Code / Cowork / Stitch 등 최신 툴 활용법
- AI 툴 조합 워크플로우 (어떤 상황에 어떤 조합)
- AI로 실제 결과물 만드는 법 (앱, 블로그, 디자인 등)
- 초보자가 자주 막히는 문제 + 해결법

## 금지 주제
- "vibe coding이란?", "AI 코딩이란?" 등 기초 입문
- Cursor/Windsurf/Bolt 기본 사용법 (오래된 내용)

JSON만 출력:
{{
  "topic": "오늘의 교육 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유 + 중복 피한 방법",
  "search_queries": ["심화 검색 쿼리1", "심화 검색 쿼리2", "실전 적용 쿼리"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=1200)
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
# STEP 3: 블로그 글 생성 (v6.1: 본문 먼저 → 제목 나중)
# ═════════════════════════════════════════════════════════════════════════════
def generate_post(track: str, topic_data: dict, deep_news: str) -> dict:
    log.info("✍️  블로그 글 작성 시작...")
    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")
    topic = topic_data["topic"]

    base_rules = f"""
블로그명: 바이브코딩 스쿨 (VIBE CODING School)
오늘 날짜: {today} ({year}년 기준으로만 작성)
오늘 주제: {topic}

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

## ⚠️ 제목 숫자/키워드 규칙 (매우 중요)
- 본문에서 실제로 다루는 단계/방법/팁의 개수를 먼저 확인하고 작성할 것
- "12가지", "7단계", "5가지" 같은 숫자는 본문 실제 개수와 반드시 일치해야 함
- 본문 작성 전에 몇 가지를 다룰지 먼저 결정하고 그 숫자에 맞춰 작성

## ⚠️ 마무리 규칙 (매우 중요)
- "다음 편에서는", "다음 글에서는", "내일은" 같은 예고 문구 절대 사용 금지
- 마무리는 오늘 다룬 내용 핵심 요약으로만 끝낼 것
"""

    if track == "news":
        news_list    = topic_data.get("news_list", [])
        todays_pick  = topic_data.get("todays_pick", "")
        todays_tool  = topic_data.get("todays_pick_tool", "")
        news_bullets = "\n".join([
            f"- [{n.get('tool','')}] {n['title']}: {n['summary']}"
            for n in news_list
        ])

        structure = f"""
## 뉴스 트랙 글 구조 (반드시 이 구조로 작성)

### 파트 1: 오늘의 AI 코딩 뉴스 브리핑
오늘의 주요 뉴스 {len(news_list)}개를 각각 뉴스 카드 형태로 작성.
각 뉴스마다:
- 무슨 일이 있었는지 (2~3줄)
- 이게 왜 중요한지 (1줄 해설)

오늘의 뉴스 목록:
{news_bullets}

### 파트 2: 🎯 오늘의 픽 — {todays_pick} ({todays_tool})
오늘 가장 핫한 것을 골라서 실전 튜토리얼로 자세히 알려줘.
- 이게 뭔지 쉽게 설명 (2~3줄)
- 실제로 어떻게 쓰는지 단계별 가이드 (정확히 5단계만 — 5개 카드로 작성)
- 막히는 포인트 + 해결법 (정확히 3가지)
- 실제 활용 예시 (정확히 3가지)

### 파트 3: 마무리
오늘 소식 핵심 한 줄 정리 (예고 문구 없이)

분량: 전체 2500~3000자
"""

    elif track == "tool":
        tool = topic_data.get("tool", "AI 도구")
        structure = f"""
## 툴 트랙 글 구조 ({tool})

1. 공감 도입 — 이런 상황에 딱!
2. {tool} 최신 업데이트 핵심 변경사항 (정확히 3가지만 — 3개로 제한)
3. 단계별 실전 가이드 (정확히 6단계 — 6개 카드로 작성)
4. 실제 결과물 예시 (정확히 2가지)
5. 자주 막히는 포인트 + 해결법 (정확히 3가지)
6. 마무리 — 오늘 핵심 요약 (예고 문구 없이)

분량: 2500~3000자
"""

    else:  # edu
        structure = """
## 교육 트랙 글 구조

1. 공감 도입
2. 필요한 도구 + 준비물 (정확히 3가지 이내)
3. 단계별 실전 방법 (정확히 5단계 — 5개 카드로 작성)
4. 실제 활용 예시 (정확히 3가지)
5. 주의사항 + 흔한 실수 (정확히 3가지)
6. 마무리 — 오늘 핵심 요약 (예고 문구 없이)

분량: 2500~3000자
"""

    # ── [v6.1] 1단계: HTML 본문 먼저 생성 ──────────────────────────────────
    log.info("  ✍️  1단계: HTML 본문 생성 중...")
    html_prompt = f"""
{base_rules}
{structure}

수집된 최신 정보:
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}

## HTML 스타일 가이드 (반드시 적용)

1. 핵심 요약 박스 (글 상단 필수 1개):
<div style="background:#F3F0FF;border-left:4px solid #6366F1;border-radius:0 8px 8px 0;padding:16px 20px;margin:24px 0"><p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#4338CA">💡 핵심 포인트</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.7">내용</p></div>

2. 뉴스 카드 (뉴스 트랙 파트1용):
<div style="background:#fff;border:1px solid #E0E7FF;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#6366F1;color:#fff;font-size:12px;font-weight:700;padding:4px 10px;border-radius:20px;flex-shrink:0;white-space:nowrap">도구명</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1E1B4B">뉴스 제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용 + 왜 중요한지</p></div></div>

3. 번호 카드 (단계별 가이드용):
<div style="background:#fff;border:1px solid #E0E7FF;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#6366F1;color:#fff;font-size:14px;font-weight:700;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0">1</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1E1B4B">단계 제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용</p></div></div>

4. 오늘의 픽 / 팁 박스:
<div style="background:#EEF2FF;border-radius:12px;padding:16px 20px;margin:20px 0"><p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#6366F1">🎯 오늘의 픽</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.6">내용 <mark style="background:#C7D2FE;color:#3730A3;padding:2px 6px;border-radius:4px">강조 키워드</mark></p></div>

5. h2 섹션 제목:
<h2 style="font-size:18px;font-weight:700;color:#1E1B4B;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #6366F1">섹션 제목</h2>

6. 일반 본문:
<p style="font-size:16px;color:#374151;line-height:1.8;margin:20px 0">내용</p>

규칙:
- 마크다운 (**굵게**, *기울임*, ## 제목) 절대 금지
- 굵게는 반드시 <strong> 태그
- 줄바꿈은 <br> 또는 <p> 태그
- 완성된 HTML만 출력, JSON/마크다운 코드블록 금지
"""
    content_html = call_claude_raw(html_prompt, max_tokens=8000)

    if content_html.startswith("```"):
        lines = content_html.split("\n")
        content_html = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    content_html = clean_markdown(content_html)
    log.info(f"  ✅ HTML 본문 생성 완료 ({len(content_html)}자)")

    # ── [v6.1] 2단계: 본문 기반으로 메타데이터(제목) 생성 ──────────────────
    log.info("  📋 2단계: 본문 기반 메타데이터 생성 중...")
    meta_prompt = f"""
아래 블로그 본문을 읽고 메타데이터를 생성해줘.

## 블로그 본문 (HTML):
{content_html[:3000]}  ← 본문 앞부분 참고

## SEO 제목 규칙
- 형식: [핵심 키워드] + [구체적 방법/결과] + [{year}]
- ⚠️ 숫자가 들어간다면 반드시 본문에서 실제로 다루는 개수와 일치해야 함
  - 단계(Step) 카드 개수, 팁 개수, 방법 개수 등을 직접 세서 반영
  - 없는 숫자 넣기 금지
- 클릭베이트 절대 금지 ("충격!", "경악!", "혁명!", "드디어" 등)
- 본문에서 실제로 다루는 내용만 제목에 포함

## 태그 규칙
- 총 3~5개만
- 필수 1~2개: Claude, 바이브코딩, AI코딩, 앱개발, AI자동화, AI에이전트, 초보자가이드
- 선택 (핵심 주제일 때만): GitHub, Cursor, Windsurf, Lovable, Perplexity, Gemini, OpenAI

JSON만 출력 (코드블록 없이):
{{
  "title_candidates": [
    "본문 내용에 정확히 부합하는 SEO 제목 1 ({year})",
    "본문 내용에 정확히 부합하는 SEO 제목 2 ({year})",
    "본문 내용에 정확히 부합하는 SEO 제목 3 ({year})",
    "본문 내용에 정확히 부합하는 SEO 제목 4 ({year})",
    "본문 내용에 정확히 부합하는 SEO 제목 5 ({year})"
  ],
  "meta_description": "구글 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3"],
  "slug": "seo-english-slug-{year}"
}}
"""
    meta_data = call_claude(meta_prompt, max_tokens=800)
    meta_data["content_html"] = content_html
    log.info("  ✅ 메타데이터 생성 완료")
    return meta_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: SEO 제목 선택
# ═════════════════════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
    log.info("🔍 SEO 제목 최적화...")
    candidates = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(post_data["title_candidates"])
    )
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""다음 제목 후보 중 SEO에 가장 좋은 제목 1개만 출력 (번호 없이).
기준: 핵심 키워드 앞배치, 숫자가 있다면 본문 실제 내용과 일치, 클릭베이트 없음, 자연스러운 표현

후보:
{candidates}""",
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4-B: [NEW v6.2] 제목-내용 일치 검증 및 자동 수정
# ═════════════════════════════════════════════════════════════════════════════
def verify_title_content_match(title: str, content_html: str) -> str:
    """
    제목과 본문 내용의 일치 여부를 Claude로 검증.
    불일치(특히 숫자/키워드)가 발견되면 본문에 맞는 제목으로 자동 교체.
    최대 2회 재시도 후 그래도 안 되면 원본 제목 반환.
    """
    log.info("🔎 제목-내용 일치 검증 중...")

    year = datetime.now().year
    # 본문 전체가 너무 길 수 있으니 앞 4000자만 전달
    content_preview = content_html[:4000]

    for attempt in range(2):
        verify_prompt = f"""
아래 블로그 제목과 본문을 검토하고, 불일치가 있으면 수정된 제목을 반환해줘.

## 현재 제목
{title}

## 본문 앞부분 (HTML)
{content_preview}

## 검증 기준
1. 숫자 일치: 제목에 "N가지", "N단계", "N개" 같은 숫자가 있다면,
   본문에서 실제로 그 개수만큼 항목이 있는지 세어봐.
   - 번호 카드(①②③ 또는 숫자 원형 아이콘)의 실제 개수를 직접 세어볼 것.
   - 제목 숫자 ≠ 본문 실제 개수이면 → 불일치
2. 핵심 키워드 일치: 제목에 언급된 도구명/기능명이 본문에서 실제로 다뤄지는지 확인.
3. 과장 표현 금지: 본문에 없는 내용을 제목이 암시하면 → 불일치

## 출력 형식 (JSON, 코드블록 없이)
일치하면:
{{"status": "ok", "title": "{title}"}}

불일치이면:
{{"status": "fixed", "title": "본문 내용에 정확히 부합하는 수정된 제목 ({year})", "reason": "수정 이유 한 줄"}}
"""
        result = call_claude(verify_prompt, max_tokens=300)
        status = result.get("status", "ok")
        new_title = result.get("title", title).strip()

        if status == "ok":
            log.info("  ✅ 검증 통과 — 제목과 내용 일치")
            return new_title
        else:
            reason = result.get("reason", "")
            log.warning(f"  ⚠️ 불일치 감지 (시도 {attempt+1}/2): {reason}")
            log.info(f"  🔧 제목 수정: {title} → {new_title}")
            title = new_title  # 수정된 제목으로 다음 검증 진행

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


def post_to_blogger(title: str, post_data: dict, image_url: str) -> str:
    log.info("📤 Blogger 포스팅 중...")
    if not image_url:
        image_url = "https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School"

    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_url}" alt="{title}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>

{post_data['content_html']}

<hr style="margin:3rem 0;border:none;border-top:1px solid #eee;" />
<div style="background:#f0f4ff;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>바이브코딩 스쿨</strong>은 코딩 없이도 AI로 앱을 만들 수 있도록
    매일 아침·저녁 최신 내용을 업데이트합니다. 구독하고 놓치지 마세요! 🔔
  </p>
</div>
"""
    service = get_blogger_service()
    result = service.posts().insert(
        blogId=BLOGGER_BLOG_ID,
        body={
            "title": title,
            "content": full_html,
            "labels": post_data.get("tags", []),
        },
        isDraft=False,
    ).execute()
    post_url = result.get("url", "URL 없음")
    log.info(f"  ✅ 포스팅 완료: {post_url}")
    return post_url


# ═════════════════════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 바이브코딩 스쿨 자동화 시작 (v6.2)")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 트랙: {track.upper()}")

        # [v6.1] 중복 방지 컨텍스트 준비
        log.info("📋 중복 방지 히스토리 로드 중...")
        history         = load_history()
        blogger_titles  = get_blogger_recent_titles(max_results=20)
        avoid_context   = build_avoid_context(history, blogger_titles)
        log.info(f"  ✅ 히스토리 {len(history['posts'])}개 + Blogger 제목 {len(blogger_titles)}개 로드")

        # 주제 결정 (중복 방지 컨텍스트 전달)
        topic_data   = decide_topic(track, avoid_context, tool_name)
        deep_news    = collect_deep_news(topic_data)

        # [v6.1] 본문 먼저 → 제목 나중
        post_data    = generate_post(track, topic_data, deep_news)
        best_title   = select_best_title(post_data)

        # [v6.2] 제목-내용 일치 검증 및 자동 수정
        best_title   = verify_title_content_match(best_title, post_data["content_html"])

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)
        image_url    = upload_image_to_imgur(image_b64)

        blog_url = post_to_blogger(best_title, post_data, image_url)

        # [v6.1] 히스토리에 기록
        add_to_history(
            history,
            title=best_title,
            topic=topic_data["topic"],
            tool=topic_data.get("tool") or topic_data.get("todays_pick_tool", ""),
            track=track,
        )
        log.info("  ✅ 히스토리 업데이트 완료")

        # 추가 채널 포스팅 (인스타, 유튜브, Threads)
        card_image_urls = []
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
