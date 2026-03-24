"""
AI Tools & Productivity Guide — Blog Automation v1
──────────────────────────────────────────────────────────
Track configuration:
  Morning 9AM → 📰 News Track: Latest AI tools & productivity news
  Evening 9PM → 📚 Tutorial Track / 🛠️ Tool Review Track (alternating)

Tool rotation: Claude → Perplexity → Cursor → Windsurf →
              Lovable → Gemini → ChatGPT → GitHub Copilot → repeat
"""

import os
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
BLOGGER_BLOG_ID    = "4418070294313014051"
GOOGLE_CREDENTIALS = os.environ["GOOGLE_CREDENTIALS_JSON"]

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

TOOL_LIST = [
    "Claude (Anthropic)",
    "Perplexity AI",
    "Cursor",
    "Windsurf",
    "Lovable",
    "Google Gemini",
    "ChatGPT",
    "GitHub Copilot",
]


# ═════════════════════════════════════════════════════════════════════════════
# Utilities
# ═════════════════════════════════════════════════════════════════════════════
def extract_text(response) -> str:
    texts = []
    for block in response.content:
        if hasattr(block, "text") and isinstance(block.text, str) and block.text.strip():
            texts.append(block.text.strip())
    return "\n".join(texts)


def search(query: str, max_tokens: int = 2000) -> str:
    today = datetime.now().strftime("%B %d, %Y")
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
                    "content": f"Today is {today}. Search for '{query}' and summarize the key findings in English.",
                }],
            )
            return extract_text(response)
        except Exception as e:
            wait = 30 * (attempt + 1)
            log.warning(f"  ⚠️ Search failed '{query}' (attempt {attempt+1}/3): {e}")
            time.sleep(wait)
    return ""


def call_claude(prompt: str, max_tokens: int = 4000) -> dict:
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
            log.warning(f"  ⚠️ Claude call failed (attempt {attempt+1}/3): {e}")
            time.sleep(wait)
    raise RuntimeError("Claude API failed after 3 attempts")


def get_track() -> tuple:
    now = datetime.now()
    if now.hour < 12:
        return "news", None
    if now.timetuple().tm_yday % 2 == 0:
        tool = TOOL_LIST[(now.timetuple().tm_yday // 2) % len(TOOL_LIST)]
        return "tool", tool
    return "tutorial", None


# ═════════════════════════════════════════════════════════════════════════════
# Image Upload
# ═════════════════════════════════════════════════════════════════════════════
def upload_image_to_imgur(image_b64: str) -> str:
    if not image_b64:
        return ""
    try:
        log.info("☁️  Uploading image to imgur...")
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
            log.info(f"  ✅ imgur upload complete: {img_url}")
            return img_url
        return ""
    except Exception as e:
        log.warning(f"  ⚠️ imgur upload failed ({e})")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: Decide today's topic
# ═════════════════════════════════════════════════════════════════════════════
def decide_topic(track: str, tool_name: str = None) -> dict:
    log.info(f"🧠 [{track.upper()}] Deciding today's topic...")

    year  = datetime.now().year
    today = datetime.now().strftime("%B %d, %Y")

    if track == "news":
        trend1 = search(f"AI productivity tools news {year} latest update")
        trend2 = search(f"Claude ChatGPT Gemini Perplexity new features {year}")
        trend3 = search(f"AI coding tools vibe coding productivity {year} trending")
        context = f"[AI Tools News]\n{trend1}\n\n[Major AI Updates]\n{trend2}\n\n[Coding & Productivity]\n{trend3}"
        prompt = f"""
Today is {today}. Here are the latest AI tools and productivity trends:
{context}

Decide the best news post topic for 'AI Tools & Productivity Guide' blog.
- Focus on what's trending TODAY
- Target audience: professionals, freelancers, entrepreneurs who want to use AI
- No basic "what is AI" topics — readers already know the basics

Output JSON only (no code blocks):
{{
  "topic": "Specific news topic for today (one sentence)",
  "reason": "Why this topic was chosen",
  "search_queries": ["follow-up search query 1", "follow-up search query 2"]
}}
"""

    elif track == "tool":
        trend1 = search(f"{tool_name} new features update {year} latest")
        trend2 = search(f"{tool_name} tips tricks productivity {year}")
        trend3 = search(f"{tool_name} vs alternatives comparison {year}")
        prompt = f"""
Today is {today}. Tool to cover: {tool_name}

Latest info:
[New Features]
{trend1}
[Tips & Tricks]
{trend2}
[Comparisons]
{trend3}

Decide the best tool review/tutorial topic for '{tool_name}'.
- Based on {year} latest updates
- Practical, actionable content for non-technical users
- Example: "Claude's New Feature That Replaces 3 Productivity Apps", "5 Perplexity Tips Power Users Don't Share"

Output JSON only (no code blocks):
{{
  "topic": "Specific tool review topic (one sentence)",
  "tool": "{tool_name}",
  "reason": "Why this topic was chosen",
  "search_queries": ["follow-up search query 1", "follow-up search query 2"]
}}
"""

    else:  # tutorial
        trend1 = search(f"AI productivity workflow automation tutorial {year}")
        trend2 = search(f"best AI tools for work business {year} guide")
        prompt = f"""
Today is {today}. Here are trending AI productivity topics:
[Tutorial Trends]
{trend1}
[Tool Guides]
{trend2}

Decide the best tutorial topic for 'AI Tools & Productivity Guide' blog.
- Practical how-to content professionals can use immediately
- No beginner "what is AI" topics

Output JSON only (no code blocks):
{{
  "topic": "Specific tutorial topic (one sentence)",
  "reason": "Why this topic was chosen",
  "search_queries": ["follow-up search query 1", "follow-up search query 2"]
}}
"""

    topic_data = call_claude(prompt, max_tokens=500)
    log.info(f"  ✅ Topic decided: {topic_data['topic']}")
    return topic_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: Collect deep research
# ═════════════════════════════════════════════════════════════════════════════
def collect_deep_research(topic_data: dict) -> str:
    log.info("📡 Collecting deep research...")
    results = []
    for q in topic_data.get("search_queries", []):
        text = search(q)
        if text:
            results.append(f"[{q}]\n{text}")
    combined = "\n\n".join(results)
    log.info(f"  ✅ Research collected ({len(combined)} chars)")
    return combined


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: Generate blog post
# ═════════════════════════════════════════════════════════════════════════════
def generate_post(track: str, topic_data: dict, deep_research: str) -> dict:
    log.info("✍️  Writing blog post...")
    year  = datetime.now().year
    today = datetime.now().strftime("%B %d, %Y")
    topic = topic_data["topic"]

    base_rules = f"""
Blog name: AI Tools & Productivity Guide
Today's date: {today} (write only in {year} context)
Today's topic: {topic}

## Writing Guidelines
- Target audience: Professionals, freelancers, entrepreneurs, students who want to use AI tools
- Tone: Helpful expert friend — clear, practical, slightly conversational
- Always explain jargon in simple terms
- Must incorporate the latest research into the post
- {year} context only (never reference outdated information)
- Never start with basic "AI is changing the world" intros — get straight to the point
- Don't just summarize sources — add unique insights and practical advice readers can act on immediately
  Example: "Here's what this means for your workflow", "Here's exactly how to set this up in 5 minutes"

## SEO Title Rules (strictly follow)
- Format: [Primary Keyword] + [Specific Result/Method] + [Audience or Year]
- Put the primary keyword at the FRONT of the title
- Include numbers when possible (e.g., "7 Ways", "In 5 Minutes", "3x Faster")
- NO clickbait: avoid "Shocking!", "Mind-blowing!", "You Won't Believe"
- Match search intent — write titles people actually search for
- Good example: "Claude AI Review {year}: Best Features for Remote Workers"
- Bad example: "This AI Tool Shocked Everyone and Changed Everything Forever"

## Tag Rules (strictly follow)
- Select 3~5 tags total
- Must include 1~2 from core tags:
  Claude, AI Tools, Productivity, Vibe Coding, App Development, AI Automation, AI Security, Beginners Guide
- Add tool-specific tags only when that tool is the main subject:
  GitHub, Cursor, Windsurf, Lovable, Perplexity, Gemini, ChatGPT, Copilot
- No tags outside this list
"""

    if track == "news":
        structure = """
## News Post Structure
1. Hook: One-line summary of today's biggest story
2. The News: What happened, explained simply
3. Why It Matters: Real impact for professionals and productivity
4. How to Use It: Practical takeaway readers can apply today
5. Today's Pick: The #1 story to watch
6. Wrap-up + preview of tomorrow
Length: 800~1,200 words
"""
    elif track == "tool":
        tool = topic_data.get("tool", "AI Tool")
        structure = f"""
## Tool Review/Tutorial Structure ({tool} latest version)
1. Hook: Who needs this tool and why (relatable scenario)
2. What's New: Latest {year} updates and key changes
3. Top 3 Features: Step-by-step with real examples
4. Common Mistakes: What beginners get wrong + fixes
5. Pro Tips: 3 power-user tips for {year}
6. Verdict: Who should use it, who shouldn't
7. Wrap-up + next tool preview
Length: 1,000~1,500 words
"""
    else:
        structure = """
## Tutorial Post Structure
1. Hook: Relatable problem this solves
2. What You'll Learn: Clear outcome promise
3. Step-by-Step Guide: Actionable instructions with examples
4. Pro Tips & Shortcuts
5. Common Pitfalls to Avoid
6. Wrap-up + next tutorial preview
Length: 1,000~1,500 words
"""

    prompt = f"""
{base_rules}

## Research & Latest Information
{deep_research if deep_research else f"{topic} latest information {year}"}

{structure}

## Output (JSON only, no code blocks)
{{
  "title_candidates": [
    "[Keyword] + [Result/Method] + [Audience or {year}] — SEO title 1 (no clickbait)",
    "[Keyword] + [Result/Method] + [Audience or {year}] — SEO title 2 (no clickbait)",
    "[Keyword] + [Result/Method] + [Audience or {year}] — SEO title 3 (no clickbait)",
    "[Keyword] + [Result/Method] + [Audience or {year}] — SEO title 4 (no clickbait)",
    "[Keyword] + [Result/Method] + [Audience or {year}] — SEO title 5 (no clickbait)"
  ],
  "meta_description": "Google-optimized meta description under 155 characters",
  "tags": ["tag1", "tag2", "tag3"],
  "slug": "seo-english-slug-{year}",
  "content_html": "Complete HTML post body (use h2 h3 p ul li strong)"
}}
"""
    post_data = call_claude(prompt)
    log.info("  ✅ Blog post generated")
    return post_data


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: Select best SEO title (double filter)
# ═════════════════════════════════════════════════════════════════════════════
def select_best_title(post_data: dict) -> str:
    log.info("🔍 Optimizing SEO title...")
    candidates = "\n".join(
        f"{i+1}. {t}" for i, t in enumerate(post_data["title_candidates"])
    )
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": f"""From the title candidates below, select the ONE that best matches these SEO rules. Output only the title (no number).

## SEO Selection Criteria
- Primary keyword appears at the FRONT of the title
- Follows [Keyword] + [Result/Method] + [Audience or Year] format
- NO clickbait words: "Shocking", "Mind-blowing", "Won't believe", "Changed everything"
- Contains numbers if possible (e.g., "5 Ways", "3x Faster")
- Sounds like something a real person would search on Google

Candidates:
{candidates}""",
        }],
    )
    title = response.content[0].text.strip()
    log.info(f"  ✅ Selected title: {title}")
    return title


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Generate image prompt
# ═════════════════════════════════════════════════════════════════════════════
def generate_image_prompt(title: str, post_data: dict) -> str:
    log.info("🖼️  Generating image prompt...")
    tags = ", ".join(post_data.get("tags", []))
    response = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=150,
        messages=[{
            "role": "user",
            "content": (
                f"Create a blog thumbnail image prompt under 50 words.\n"
                f"Title: {title}\nTags: {tags}\n\n"
                "Requirements: bright tech illustration, no text, 16:9 ratio.\n"
                "Output prompt only:"
            ),
        }],
    )
    prompt = response.content[0].text.strip()
    log.info(f"  ✅ Prompt: {prompt[:60]}...")
    return prompt


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: Generate thumbnail
# ═════════════════════════════════════════════════════════════════════════════
def generate_thumbnail(image_prompt: str) -> str:
    log.info("🎨 Generating thumbnail...")
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
                log.info("  ✅ Thumbnail generated")
                return part["inlineData"]["data"]
        raise ValueError("No image data")
    except Exception as e:
        log.warning(f"  ⚠️ Thumbnail generation failed ({e})")
        return ""


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7: Post to Blogger
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


def post_to_blogger(title: str, post_data: dict, image_b64: str) -> str:
    log.info("📤 Posting to Blogger...")

    image_url = upload_image_to_imgur(image_b64)
    if not image_url:
        image_url = "https://placehold.co/1200x630/6366f1/ffffff?text=AI+Tools+Guide"
        log.info("  ℹ️  Using placeholder image")

    full_html = f"""
<div style="margin-bottom:2rem;">
  <img src="{image_url}" alt="{title}"
       style="width:100%;border-radius:12px;max-height:420px;object-fit:cover;" />
</div>

{post_data['content_html']}

<hr style="margin:3rem 0;border:none;border-top:1px solid #eee;" />
<div style="background:#f0f4ff;padding:1.5rem;border-radius:8px;margin-top:2rem;">
  <p style="margin:0;font-size:0.9rem;color:#555;">
    📌 <strong>AI Tools & Productivity Guide</strong> publishes daily guides on the best AI tools
    to help you work smarter. Subscribe and never miss an update! 🔔
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
    post_url = result.get("url", "No URL")
    log.info(f"  ✅ Posted: {post_url}")
    return post_url


# ═════════════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════════════
def main():
    log.info("=" * 60)
    log.info("🚀 AI Tools & Productivity Guide — Automation Start")
    log.info(f"   Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log.info("=" * 60)

    try:
        track, tool_name = get_track()
        log.info(f"  📌 Track: {track.upper()}" + (f" | Tool: {tool_name}" if tool_name else ""))

        topic_data    = decide_topic(track, tool_name)
        deep_research = collect_deep_research(topic_data)
        post_data     = generate_post(track, topic_data, deep_research)
        best_title    = select_best_title(post_data)

        image_prompt = generate_image_prompt(best_title, post_data)
        image_b64    = generate_thumbnail(image_prompt)

        blog_url = post_to_blogger(best_title, post_data, image_b64)

        log.info("=" * 60)
        log.info("🎉 Pipeline complete!")
        log.info(f"   Track: {track.upper()} | Topic: {topic_data['topic']}")
        log.info(f"   Blog URL: {blog_url}")
        log.info("=" * 60)

    except Exception as e:
        log.error(f"❌ Automation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
