"""
바이브코딩 스쿨 (VIBE CODING School) — Blog Automation v4
──────────────────────────────────────────────────────────
트랙 구성:
  아침 9시 → 📰 뉴스 트랙: 오늘의 AI 코딩 최신 소식
  저녁 9시 → 📚 교육 트랙 / 🛠️ 툴 사용법 트랙 (하루씩 번갈아)

v4.2 수정사항:
  - 툴 트랙 고정 순환 완전 제거 → AI가 오늘 가장 핫한 툴 자동 선택
  - 뉴스 트랙: 정책/요금 변경, 보안 이슈, 업계 동향 추가
  - 교육 트랙: 실전 자동화, 도구 비교, 수익화 주제 추가
  - 툴 트랙: 실전편 (코딩 없이 따라하기) 추가
  - 유튜브 쇼츠 자동 업로드 추가 (썸네일 + Orus 음성)
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
    """마크다운 잔여물을 HTML 태그로 변환"""
    html = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', html)
    html = re.sub(r'\*(.+?)\*', r'<em>\1</em>', html)
    html = re.sub(r'^#{1,6}\s+(.+)$', r'<h3>\1</h3>', html, flags=re.MULTILINE)
    return html


def search(query: str, max_tokens: int = 2000) -> str:
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
                    "content": f"오늘({today}) 기준으로 '{query}'를 검색하고 핵심 내용을 한국어로 요약해줘.",
                }],
            )
            return extract_text(response)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ 검색 실패 '{query}' (시도 {attempt+1}/3): {e}")
            log.warning(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
    return ""


def call_claude(prompt: str, max_tokens: int = 4000) -> dict:
    """메타데이터 전용 — JSON 파싱 (HTML 포함 금지)"""
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
            log.warning(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def call_claude_raw(prompt: str, max_tokens: int = 4000) -> str:
    """HTML 본문 전용 — JSON 파싱 없이 텍스트 그대로 반환"""
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
            log.warning(f"  ⏳ {wait}초 대기 후 재시도...")
            time.sleep(wait)
    raise RuntimeError("Claude API 호출 3회 모두 실패")


def get_track() -> tuple:
    """
    아침(hour < 12) → news
    저녁 홀수일     → edu
    저녁 짝수일     → tool (AI가 오늘 가장 핫한 툴 자동 선택)
    """
    now = datetime.now()
    if now.hour < 12:
        return "news", None
    if now.timetuple().tm_yday % 2 == 0:
        return "tool", None  # ✅ 고정 순환 제거
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
        log.warning(f"  ⚠️ imgur 응답 실패: {data}")
        return ""
    except Exception as e:
        log.warning(f"  ⚠️ imgur 업로드 실패 ({e}), placehold 사용")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: AI가 오늘의 주제를 스스로 결정
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, tool_name: str = None) -> dict:
    log.info(f"🧠 [{track.upper()}] 오늘의 주제 AI 자동 결정 중...")

    year  = datetime.now().year
    today = datetime.now().strftime("%Y년 %m월 %d일")

    if track == "news":
        trend1 = search(f"Claude Anthropic AI coding update policy pricing {year} latest")
        trend2 = search(f"Cursor Windsurf Lovable Bolt vibe coding news {year} latest")
        trend3 = search(f"OpenAI Gemini Perplexity AI coding policy pricing change {year} latest")
        context = f"[Anthropic/Claude]\n{trend1}\n\n[Cursor/Windsurf/Lovable/Bolt]\n{trend2}\n\n[OpenAI/Gemini/Perplexity 정책/요금]\n{trend3}"
        prompt = f"""
오늘({today}) AI 코딩 업계 최신 트렌드 정보입니다:
{context}

위 정보를 바탕으로 오늘 '바이브코딩 스쿨' 블로그의 뉴스 포스트 주제를 결정해줘.

아래 주제 유형 중 오늘 가장 화제인 것을 선택해줘:
- AI 코딩 도구 신기능/업데이트 소식
- Claude/Gemini/OpenAI/Perplexity 정책 또는 요금 변경
- AI 코딩 도구 간 비교/순위 변화
- 바이브코딩 관련 업계 동향 (기업 도입, 시장 변화)
- AI 보안/개인정보 이슈
- 한국 개발자/직장인에게 직접 영향을 주는 변화

조건:
- 오늘 가장 화제가 되는 내용 중심
- 한국 일반인 독자가 관심 가질 주제
- "vibe coding이란?" 같은 기초 주제 절대 금지

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 뉴스 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    elif track == "tool":
        trend1 = search(f"AI coding tool trending hot update {year} latest")
        trend2 = search(f"바이브코딩 AI 도구 인기 신기능 {year} 최신")
        prompt = f"""
오늘({today}) AI 코딩 도구 트렌드입니다:
[글로벌 트렌드]
{trend1}
[한국 트렌드]
{trend2}

위 정보를 바탕으로 오늘 다룰 AI 코딩 도구를 직접 선택하고, 포스트 주제를 결정해줘.

선택 가능한 도구 예시 (오늘 핫한 도구면 이 외에도 선택 가능):
Claude, ChatGPT, Gemini, Perplexity, Cursor, Windsurf, Lovable, Bolt.new,
Replit, GitHub Copilot, Google AI Studio, Devin, v0, Codeium, Tabnine,
NotebookLM, Midjourney, Canva AI, Notion AI 등

주제 유형 (아래 중 오늘 가장 적합한 것 선택):
- 최신 업데이트/신기능 실전 사용법
- 코딩 없이 따라하는 실전편 (단계별 가이드)
- 초보자가 바로 써먹는 꿀팁 모음
- 다른 도구와 비교해서 언제 쓰면 좋은지
- 특정 업무(블로그, 쇼핑몰, 자동화 등)에 활용하는 법

조건:
- {year}년 최신 업데이트 기반
- 코딩 0% 초보자도 따라할 수 있는 실용적인 주제
- 실제로 써먹을 수 있는 내용 (단순 소개 금지)

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 툴 주제 (한 문장)",
  "tool": "선택한 AI 도구 이름",
  "reason": "이 도구와 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    else:  # edu
        trend1 = search(f"vibe coding 실전 자동화 튜토리얼 {year} Korea")
        trend2 = search(f"AI coding tool comparison workflow automation {year}")
        prompt = f"""
오늘({today}) AI 코딩/자동화 관련 트렌드입니다:
[실전/튜토리얼 트렌드]
{trend1}
[도구 비교/워크플로우 트렌드]
{trend2}

위 정보를 바탕으로 오늘 '바이브코딩 스쿨' 블로그의 교육 포스트 주제를 결정해줘.

아래 주제 유형 중 오늘 가장 적합한 것 선택:
- 실전 자동화 가이드 (블로그/SNS/업무 자동화, 코딩 없이 따라하기)
- AI 도구 비교 (어떤 상황에 어떤 도구가 맞는지)
- AI로 수익 내는 실전 방법 (부업, 프리랜서, 콘텐츠 제작)
- 직장인/소상공인이 바로 쓰는 AI 활용법
- 초보자가 자주 막히는 문제 + 해결법
- AI 에이전트 활용 실전 가이드

조건:
- 코딩 0% 초보자가 실제로 따라할 수 있는 내용
- "vibe coding이란?", "AI 코딩이란?" 같은 기초 입문 주제 절대 금지
- 읽고 나서 바로 실행할 수 있는 구체적인 주제

JSON만 출력 (코드블록 없이):
{{
  "topic": "오늘의 구체적인 교육 주제 (한 문장)",
  "reason": "이 주제를 선택한 이유",
  "search_queries": ["추가로 검색할 쿼리1", "추가로 검색할 쿼리2"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=500)
    log.info(f"  ✅ 결정된 주제: {topic_data['topic']}")
    log.info(f"  💡 선택 이유: {topic_data['reason']}")
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
# STEP 3: 블로그 글 생성 (메타 + 본문 분리)
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
- 독자: 코딩 0% 일반인 (직장인, 소상공인, 주부, 학생)
- 어조: 친근한 선생님 ("~해요", "~거예요", "~네요")
- 전문용어 나오면 반드시 쉽게 풀어서 설명
- 수집된 최신 정보 반드시 본문에 녹여낼 것
- {year}년 현재 기준 (다른 연도 절대 금지)
- "vibe coding이란?", "AI 코딩이란?" 같은 기초 설명으로 글 시작 금지
- 수집된 정보를 단순 요약하지 말고, 한국 독자(직장인/취준생/소상공인) 관점의 인사이트와 의견을 반드시 추가할 것

## SEO 제목 규칙 (반드시 준수)
- 형식: [핵심 키워드] + [구체적 방법/결과] + [대상 또는 연도]
- 핵심 키워드를 제목 앞부분에 배치
- 숫자 포함 권장 (예: "3가지", "5분 만에", "10배")
- 클릭베이트 절대 금지: "충격!", "경악!", "혁명!", "난리났다", "드디어" 사용 금지
- 좋은 예: "Claude Code로 앱 만드는 법 - 초보자 완전 가이드 {year}"
- 나쁜 예: "충격! AI가 드디어 해냈다! 개발자들 멘붕"

## 태그 규칙 (반드시 준수)
- 글당 총 3~5개만 선택
- 아래 필수 태그 중 1~2개 반드시 포함:
  Claude, 바이브코딩, AI코딩, 앱개발, AI자동화, AI보안, AI에이전트, 초보자가이드
- 아래 선택 태그는 해당 툴이 글의 핵심 주제일 때만 추가:
  GitHub, Cursor, Windsurf, Lovable, Perplexity, Gemini, OpenAI
- 이 목록 외의 태그는 절대 생성 금지
"""

    if track == "news":
        structure = """
## 뉴스 트랙 글 구조
1. 오늘의 핵심 소식 한 줄 요약으로 시작
2. 각 소식별 쉬운 설명 + "이게 왜 중요한가" 한 줄 해설
3. 독자에게 미치는 영향 (한국 직장인/취준생 관점으로 구체적으로)
4. 오늘의 픽: 가장 주목할 소식 1개 강조
5. 마무리 + 내일 예고
분량: 2000~2500자
"""
    elif track == "tool":
        tool = topic_data.get("tool", "AI 도구")
        structure = f"""
## 툴 트랙 글 구조 ({tool} 기준)
아래 유형 중 오늘 주제에 맞는 구조 선택:

[실전편 - 코딩 없이 따라하기]
1. "이런 분들께 딱!" 공감 도입
2. 준비물 (계정, 설치 등 최소화)
3. 단계별 실전 가이드 (스크린샷 설명하듯 구체적으로, 5~7단계)
4. 실제 결과물 예시
5. 자주 막히는 포인트 + 해결법
6. 마무리 + 다음 편 예고
분량: 2500~3000자

[사용법/기능 소개]
1. "이런 분들께 딱!" 공감 도입
2. {tool} 최신 업데이트 핵심 변경사항
3. 핵심 기능 3가지 실전 사용법
4. 초보자가 자주 하는 실수 + 해결법
5. {year}년 기준 꿀팁 3가지
6. 마무리 + 다음 툴 예고
분량: 2500~3000자
"""
    else:
        structure = """
## 교육 트랙 글 구조
아래 유형 중 오늘 주제에 맞는 구조 선택:

[실전 자동화 가이드]
1. 공감 도입 (이걸 자동화하면 이런 게 해결돼요)
2. 필요한 도구 소개 (무료/유료 구분)
3. 단계별 자동화 세팅 방법 (최대한 구체적으로)
4. 실제 활용 예시 (직장인/소상공인 케이스)
5. 주의사항 + 흔한 실수
6. 마무리 + 다음 글 예고
분량: 2500~3000자

[도구 비교 / 수익화 / 활용법]
1. 공감 도입
2. 핵심 내용 설명 (쉽게)
3. 실전 적용 방법 (단계별)
4. 현실적인 기대치 / 주의사항
5. 바로 시작하는 첫 단계
6. 마무리 + 다음 글 예고
분량: 2500~3000자
"""

    # 1단계: 메타데이터만 JSON으로 받기
    log.info("  📋 1단계: 메타데이터 생성 중...")
    meta_prompt = f"""
{base_rules}

## 수집된 최신 정보
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}

아래 JSON만 출력해줘 (코드블록 없이, HTML 절대 포함 금지):
{{
  "title_candidates": [
    "[핵심키워드] + [방법/결과] + [대상 or {year}] 형식의 SEO 제목 1 (클릭베이트 금지)",
    "[핵심키워드] + [방법/결과] + [대상 or {year}] 형식의 SEO 제목 2 (클릭베이트 금지)",
    "[핵심키워드] + [방법/결과] + [대상 or {year}] 형식의 SEO 제목 3 (클릭베이트 금지)",
    "[핵심키워드] + [방법/결과] + [대상 or {year}] 형식의 SEO 제목 4 (클릭베이트 금지)",
    "[핵심키워드] + [방법/결과] + [대상 or {year}] 형식의 SEO 제목 5 (클릭베이트 금지)"
  ],
  "meta_description": "구글 클릭률 높은 메타설명 150자 이내",
  "tags": ["태그1", "태그2", "태그3"],
  "slug": "seo-english-slug-{year}"
}}
"""
    meta_data = call_claude(meta_prompt, max_tokens=800)
    log.info("  ✅ 메타데이터 생성 완료")

    # 2단계: HTML 본문만 순수 텍스트로 받기
    log.info("  ✍️  2단계: HTML 본문 생성 중...")
    html_prompt = f"""
{base_rules}
{structure}

## 수집된 최신 정보
{deep_news if deep_news else f"{topic} 관련 {year}년 최신 정보"}

## HTML 스타일 가이드 (반드시 적용)
포인트 컬러: #6366F1 (인디고/보라) — 바이브코딩 스쿨 브랜드 색상

1. 핵심 요약 박스 (글 상단에 반드시 1개 사용):
<div style="background:#F3F0FF;border-left:4px solid #6366F1;border-radius:0 8px 8px 0;padding:16px 20px;margin:24px 0"><p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#4338CA">💡 핵심 포인트</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.7">핵심 내용</p></div>

2. 번호 카드 (단계별 설명에 사용, 3~5개):
<div style="background:#fff;border:1px solid #E0E7FF;border-radius:12px;padding:16px;display:flex;gap:16px;align-items:flex-start;margin-bottom:12px"><div style="background:#6366F1;color:#fff;font-size:14px;font-weight:700;width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0">1</div><div><p style="margin:0 0 6px;font-size:15px;font-weight:700;color:#1E1B4B">제목</p><p style="margin:0;font-size:14px;color:#4B5563;line-height:1.6">내용</p></div></div>

3. 주의/팁 박스:
<div style="background:#EEF2FF;border-radius:12px;padding:16px 20px;margin:20px 0"><p style="margin:0 0 6px;font-size:13px;font-weight:700;color:#6366F1">⚠️ 주의사항</p><p style="margin:0;font-size:14px;color:#3730A3;line-height:1.6">내용. 키워드는 <mark style="background:#C7D2FE;color:#3730A3;padding:2px 6px;border-radius:4px">이렇게 강조</mark></p></div>

4. h2 섹션 제목:
<h2 style="font-size:18px;font-weight:700;color:#1E1B4B;margin:32px 0 16px;padding-bottom:8px;border-bottom:2px solid #6366F1">섹션 제목</h2>

규칙:
- 모든 섹션에 위 스타일 중 하나 이상 반드시 사용
- 일반 텍스트 나열 금지
- 중요 키워드는 <mark style="background:#C7D2FE;color:#3730A3;padding:2px 6px;border-radius:4px">이렇게 강조</mark>
- **굵게**, *기울임*, ## 제목 같은 마크다운 문법 절대 사용 금지
- 굵게 강조할 때는 반드시 <strong> 태그 사용
- 줄바꿈은 반드시 <br> 또는 <p> 태그 사용

완성된 HTML 본문만 출력해줘. JSON 형식 금지, 마크다운 코드블록 금지, HTML 태그만 바로 출력.
"""
    content_html = call_claude_raw(html_prompt, max_tokens=4000)

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
            "content": f"""다음 제목 후보 중 아래 SEO 규칙에 가장 잘 맞는 제목 1개만 출력해줘 (번호 없이).

## SEO 선택 기준
- 핵심 키워드가 제목 앞부분에 위치할 것
- [키워드] + [방법/결과] + [대상 or 연도] 형식에 가까울 것
- "충격!", "혁명!", "경악!", "드디어", "난리났다" 같은 클릭베이트 표현이 없을 것
- 숫자가 포함된 제목 우선 선택 (예: "3가지", "5분 만에")
- 실제로 검색할 법한 자연스러운 표현일 것

후보:
{candidates}""",
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ 선택된 제목: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: 이미지 프롬프트 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    log.info("🖼️  이미지 프롬프트 생성 중...")
    tags = ", ".join(post_data.get("tags", []))
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"블로그 썸네일용 영문 이미지 프롬프트 50단어 이내로 만들어줘.\n"
                f"제목: {title}\n태그: {tags}\n\n"
                "조건: 밝고 친근한 테크 일러스트, 텍스트 없음, 16:9.\n"
                "프롬프트만 출력:"
            ),
        }],
    )
    prompt = response.content[0].text.strip()
    log.info(f"  ✅ 프롬프트: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: 이미지 생성
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    log.info("🎨 썸네일 생성 중... (Gemini 2.5 Flash Image / 무료)")
    enhanced = (
        f"{image_prompt}, modern flat illustration, vibrant colors, "
        "16:9 blog thumbnail, no text no letters, "
        "professional tech design, bright friendly"
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
        data = resp.json()
        for part in data["candidates"][0]["content"]["parts"]:
            if "inlineData" in part:
                log.info("  ✅ 이미지 생성 완료")
                return part["inlineData"]["data"]
        raise ValueError("이미지 데이터 없음")
    except Exception as e:
        log.warning(f"  ⚠️ 이미지 생성 실패 ({e}), 플레이스홀더 사용")
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
        log.info("  ℹ️  placehold 이미지 사용")

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
    log.info("🚀 바이브코딩 스쿨 자동화 시작 (v4.2)")
    log.info(f"   날짜: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 트랙: {track.upper()}")

        topic_data = decide_topic(track, tool_name)
        deep_news  = collect_deep_news(topic_data)
        post_data  = generate_post(track, topic_data, deep_news)
        best_title = select_best_title(post_data)

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)

        # imgur 업로드 (블로그 + 유튜브 공용)
        image_url = upload_image_to_imgur(image_b64)

        # ✅ 블로그 포스팅
        blog_url = post_to_blogger(best_title, post_data, image_url)

        # ✅ 유튜브 쇼츠 자동 업로드
        try:
            from youtube_shorts import post_youtube_shorts
            youtube_url = post_youtube_shorts(
                title=best_title,
                content_html=post_data["content_html"],
                image_url=image_url,
                blog_url=blog_url,
            )
            if youtube_url:
                log.info(f"  🎬 유튜브 쇼츠 완료: {youtube_url}")
        except Exception as e:
            log.warning(f"  ⚠️ 유튜브 쇼츠 실패 (블로그는 정상): {e}")

        # ✅ 인스타그램 포스팅
        try:
            from instagram import post_instagram
            insta_url = post_instagram(
                blog_title=best_title,
                blog_content_html=post_data["content_html"],
                tags=post_data.get("tags", []),
            )
            log.info(f"  📸 인스타 포스팅 완료: {insta_url}")
        except Exception as e:
            log.warning(f"  ⚠️ 인스타 포스팅 실패 (블로그는 정상): {e}")

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
