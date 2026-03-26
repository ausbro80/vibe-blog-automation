"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v6
──────────────────────────────────────────────────────────
트랙 구성:
  아침 9시 → 📰 뉴스 트랙: 오늘의 TOP AI 코딩 뉴스 요약 + 핫한 것 1개 실전 튜토리얼
  저녁 9시 → 📚 교육 트랙 / 🛠️ 툴 사용법 트랙 (하루씩 번갈아)

v6.0 수정사항:
  - 검색 쿼리 전면 개편 → 요즘 진짜 핫한 툴 중심
  - Claude Code, Cowork, Google Stitch, Gemini 2.5, Antigravity, Firebase Genkit 등
  - Cursor/Windsurf/Bolt/Replit 기본 제외 → major 업데이트 있을 때만 선택
  - 24시간 이내 최신 업데이트/핫토픽 우선 수집
  - 직장인/주부 표현 완전 제거
  - Lovable 편중 방지
"""

import os
import re
import sys
import json
import time
import logging
from datetime import datetime

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
# 이미지 업로드
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
# STEP 1: 오늘의 주제 결정 (24시간 핫토픽 기반)
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, tool_name: str = None) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    if track == "news":
        # 요즘 진짜 핫한 툴 중심으로 수집
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

위 정보를 바탕으로 오늘의 뉴스 포스트를 구성해줘.

## 뉴스 선정 원칙
- 반드시 최근 24~48시간 이내에 발생한 소식 우선
- 오래된 일반 설명 기사 제외
- 실제 업데이트/출시/정책변경/가격변경 등 구체적 뉴스 선정

## 도구 우선순위 (요즘 핫한 것)
최우선: Claude Code, Cowork, Google Stitch, Gemini 2.5, Antigravity, Firebase Genkit, Veo, Sora
보통: ChatGPT, Perplexity, GitHub Copilot, Devin, v0, NotebookLM
하위 (major 업데이트 있을 때만): Cursor, Windsurf, Bolt, Replit, Lovable

## 오늘의 픽 선정 기준
- 독자가 바로 따라해볼 수 있는 것
- 실전 튜토리얼로 만들기 좋은 것
- 오늘 가장 화제가 된 것

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
  "reason": "전체 주제 선택 이유",
  "search_queries": ["픽 심화 검색 쿼리1", "픽 심화 검색 쿼리2", "픽 실전 사용법 쿼리"]
}}
"""

    elif track == "tool":
        # 요즘 핫한 툴 중심 수집
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

오늘 다룰 AI 도구를 선택하고 포스트 주제를 결정해줘.

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

## 주제 유형
- 최신 업데이트 실전 사용법
- 코딩 없이 따라하는 단계별 가이드
- 이 도구로 실제로 만들어보기
- 다른 도구와 비교

JSON만 출력:
{{
  "topic": "오늘의 툴 주제 (한 문장)",
  "tool": "선택한 AI 도구 이름",
  "reason": "이 도구와 주제를 선택한 이유",
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

오늘 교육 포스트 주제를 결정해줘.

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
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["심화 검색 쿼리1", "심화 검색 쿼리2", "실전 적용 쿼리"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=1000)
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

## SEO 제목 규칙
- 형식: [핵심 키워드] + [구체적 방법/결과] + [{year}]
- 숫자 포함 권장
- 클릭베이트 절대 금지 ("충격!", "경악!", "혁명!", "드디어" 등)

## 태그 규칙
- 총 3~5개만
- 필수 1~2개: Claude, 바이브코딩, AI코딩, 앱개발, AI자동화, AI에이전트, 초보자가이드
- 선택 (핵심 주제일 때만): GitHub, Cursor, Windsurf, Lovable, Perplexity, Gemini, OpenAI
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
- 실제로 어떻게 쓰는지 단계별 가이드 (5~7단계)
- 막히는 포인트 + 해결법
- 실제 활용 예시

### 파트 3: 마무리
오늘 소식 한 줄 정리 + 내일 예고 (예: "내일은 ~~~를 자세히 다뤄볼게요!")

분량: 전체 2500~3000자
"""

    elif track == "tool":
        tool = topic_data.get("tool", "AI 도구")
        structure = f"""
## 툴 트랙 글 구조 ({tool})

1. 공감 도입 — 이런 상황에 딱!
2. {tool} 최신 업데이트 핵심 변경사항
3. 단계별 실전 가이드 (5~7단계, 스크린샷 설명하듯 구체적으로)
4. 실제 결과물 예시
5. 자주 막히는 포인트 + 해결법
6. 마무리 + 다음 편 예고

분량: 2500~3000자
"""

    else:  # edu
        structure = """
## 교육 트랙 글 구조

1. 공감 도입
2. 필요한 도구 + 준비물
3. 단계별 실전 방법 (최대한 구체적으로)
4. 실제 활용 예시
5. 주의사항 + 흔한 실수
6. 마무리 + 다음 글 예고

분량: 2500~3000자
"""

    # 1단계: 메타데이터
    log.info("  📋 1단계: 메타데이터 생성 중...")
    meta_prompt = f"""
{base_rules}

수집된 최신 정보:
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}

JSON만 출력 (코드블록/HTML 절대 금지):
{{
  "title_candidates": [
    "SEO 제목 1 ({year})",
    "SEO 제목 2 ({year})",
    "SEO 제목 3 ({year})",
    "SEO 제목 4 ({year})",
    "SEO 제목 5 ({year})"
  ],
  "meta_description": "구글 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3"],
  "slug": "seo-english-slug-{year}"
}}
"""
    meta_data = call_claude(meta_prompt, max_tokens=800)
    log.info("  ✅ 메타데이터 생성 완료")

    # 2단계: HTML 본문
    log.info("  ✍️  2단계: HTML 본문 생성 중...")
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
    meta_data["content_html"] = content_html
    log.info(f"  ✅ 블로그 글 생성 완료 (본문 {len(content_html)}자)")
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
기준: 핵심 키워드 앞배치, 숫자 포함, 클릭베이트 없음, 자연스러운 표현

후보:
{candidates}""",
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
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
# STEP 6: Blogger 포스팅
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
    📌 <strong>바이브코딩 스쿨</strong>은 코딩 몰라도 AI로 앱을 만들 수 있도록
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
    log.info("🚀 바이브코딩 스쿨 자동화 시작 (v6.0)")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 트랙: {track.upper()}")

        topic_data   = decide_topic(track, tool_name)
        deep_news    = collect_deep_news(topic_data)
        post_data    = generate_post(track, topic_data, deep_news)
        best_title   = select_best_title(post_data)

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)
        image_url    = upload_image_to_imgur(image_b64)

        blog_url = post_to_blogger(best_title, post_data, image_url)

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
        log.info(f"   블로그 URL: {blog_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ 자동화 실패: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
