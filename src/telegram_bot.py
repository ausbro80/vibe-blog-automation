"""
바이브코딩 스쿨 — 텔레그램 봇 핸들러
──────────────────────────────────────────────
텔레그램에서 URL 받으면 → GitHub Actions 트리거 → 블로그 + 인스타 포스팅
중복 처리 방지: last_update_id.txt 로 처리된 메시지 추적
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
GH_REPO            = os.environ.get("GH_REPO", "")

# 마지막 처리한 update_id 저장 파일
LAST_ID_FILE = "last_update_id.txt"


# ═════════════════════════════════════════════════════════════
# 텔레그램 메시지 전송
# ═════════════════════════════════════════════════════════════
def send_telegram(text: str):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception as e:
        log.warning(f"텔레그램 알림 실패: {e}")


# ═════════════════════════════════════════════════════════════
# 마지막 처리 ID 관리
# ═════════════════════════════════════════════════════════════
def get_last_update_id() -> int:
    """저장된 마지막 update_id 읽기"""
    try:
        if os.path.exists(LAST_ID_FILE):
            with open(LAST_ID_FILE, "r") as f:
                return int(f.read().strip())
    except Exception:
        pass
    return 0


def save_last_update_id(update_id: int):
    """마지막 처리한 update_id 저장"""
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(update_id))
    # GitHub에 커밋해서 다음 실행 때도 기억
    os.system(f'git config user.email "action@github.com"')
    os.system(f'git config user.name "GitHub Action"')
    os.system(f'git add {LAST_ID_FILE}')
    os.system(f'git commit -m "update last_update_id: {update_id}"')
    os.system(f'git pull --rebase origin main')
    os.system(f'git push')


# ═════════════════════════════════════════════════════════════
# 새 메시지 가져오기
# ═════════════════════════════════════════════════════════════
def get_new_messages(last_id: int) -> list:
    """last_id 이후의 새 메시지만 가져오기"""
    resp = requests.get(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates",
        params={"offset": last_id + 1, "limit": 10, "timeout": 0},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("result", [])


# ═════════════════════════════════════════════════════════════
# GitHub Actions 트리거
# ═════════════════════════════════════════════════════════════
def trigger_github_actions(url: str) -> bool:
    log.info(f"🚀 GitHub Actions 트리거: {url[:60]}...")
    resp = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/actions/workflows/telegram-post.yml/dispatches",
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
        log.info("  ✅ 트리거 성공")
        return True
    log.error(f"  ❌ 트리거 실패: {resp.status_code} {resp.text}")
    return False


# ═════════════════════════════════════════════════════════════
# 메인
# ═════════════════════════════════════════════════════════════
def main():
    log.info("=" * 50)
    log.info("📱 텔레그램 봇 메시지 체크")
    log.info("=" * 50)

    last_id  = get_last_update_id()
    log.info(f"  마지막 처리 ID: {last_id}")

    updates = get_new_messages(last_id)
    if not updates:
        log.info("  ℹ️  새 메시지 없음")
        return

    for update in updates:
        update_id = update["update_id"]
        message   = update.get("message", {})
        chat_id   = str(message.get("chat", {}).get("id", ""))
        text      = message.get("text", "").strip()

        log.info(f"  📩 메시지 수신 (ID: {update_id}): {text[:80]}")

        # 내 채팅에서 온 메시지인지 확인 (보안)
        if chat_id != TELEGRAM_CHAT_ID:
            log.warning(f"  ⚠️ 다른 사용자 무시: {chat_id}")
            save_last_update_id(update_id)
            continue

        # URL 여부 확인
        if text.startswith("http://") or text.startswith("https://"):
            send_telegram(
                f"🔍 링크 확인했어요!\n"
                f"{text[:60]}...\n\n"
                f"블로그 글 작성 시작할게요!\n"
                f"완료되면 알려드릴게요 ✍️"
            )
            success = trigger_github_actions(text)
            if not success:
                send_telegram("❌ 트리거 실패했어요. 잠시 후 다시 시도해주세요.")
        else:
            send_telegram("🔗 URL을 보내주세요!\n예: https://openai.com/blog/...")

        # 처리 완료 → ID 저장
        save_last_update_id(update_id)


if __name__ == "__main__":
    main()
