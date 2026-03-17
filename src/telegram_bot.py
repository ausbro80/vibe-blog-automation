"""
바이브코딩 스쿨 — 텔레그램 봇 핸들러
──────────────────────────────────────────────
텔레그램에서 URL 받으면 → GitHub Actions 트리거 → 블로그 + 인스타 포스팅
GitHub Actions에서 실행됨 (webhook 서버 불필요)
"""

import os
import sys
import json
import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID   = os.environ["TELEGRAM_CHAT_ID"]
GH_PAT             = os.environ["GH_PAT"]
GH_REPO            = os.environ.get("GH_REPO", "ausbro80/vibe-blog-automation")


# ═════════════════════════════════════════════════════════════
# 텔레그램 메시지 전송
# ═════════════════════════════════════════════════════════════
def send_telegram(text: str):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
        timeout=10,
    )


# ═════════════════════════════════════════════════════════════
# 텔레그램 최신 메시지 가져오기
# ═════════════════════════════════════════════════════════════
def get_latest_message() -> dict | None:
    """
    getUpdates로 최신 메시지 1개 가져오기.
    GitHub Actions에서 실행 시 마지막 메시지를 확인.
    """
    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
        params={"limit": 1, "offset": -1},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("result", [])
    if not results:
        return None
    return results[-1]


# ═════════════════════════════════════════════════════════════
# GitHub Actions workflow_dispatch 트리거
# ═════════════════════════════════════════════════════════════
def trigger_github_actions(url: str):
    log.info(f"🚀 GitHub Actions 트리거: {url[:60]}...")
    resp = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/actions/workflows/daily-post.yml/dispatches",
        headers={
            "Authorization": f"token {GH_PAT}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "ref": "main",
            "inputs": {
                "custom_url": url,
                "dry_run": "false",
            },
        },
        timeout=15,
    )
    if resp.status_code == 204:
        log.info("  ✅ GitHub Actions 트리거 성공")
        return True
    else:
        log.error(f"  ❌ 트리거 실패: {resp.status_code} {resp.text}")
        return False


# ═════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════
def main():
    log.info("=" * 50)
    log.info("📱 텔레그램 봇 체크 시작")
    log.info("=" * 50)

    update = get_latest_message()
    if not update:
        log.info("  ℹ️  새 메시지 없음")
        return

    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    text    = message.get("text", "").strip()

    # 내 채팅에서 온 메시지인지 확인 (보안)
    if chat_id != TELEGRAM_CHAT_ID:
        log.warning(f"  ⚠️ 다른 사용자 메시지 무시: {chat_id}")
        return

    log.info(f"  📩 메시지 수신: {text[:80]}")

    # URL 여부 확인
    if text.startswith("http://") or text.startswith("https://"):
        send_telegram(f"🔍 링크 확인했어요!\n{text[:60]}...\n\n블로그 글 작성 시작할게요! 완료되면 알려드릴게요 ✍️")
        success = trigger_github_actions(text)
        if not success:
            send_telegram("❌ GitHub Actions 트리거 실패했어요. 잠시 후 다시 시도해주세요.")
    else:
        send_telegram("🔗 URL을 보내주세요!\n예: https://openai.com/blog/...")
        log.info("  ℹ️  URL이 아닌 메시지 — 안내 메시지 전송")


if __name__ == "__main__":
    main()
