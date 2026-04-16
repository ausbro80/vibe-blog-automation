"""
바이브코딩 스쿨 — 텔레그램 봇 핸들러
──────────────────────────────────────────────
텔레그램에서 글 내용 받으면 → GitHub Actions 트리거 → 블로그 + 인스타 포스팅
중복 방지: update_id 체크
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
    try:
        if os.path.exists(LAST_ID_FILE):
            with open(LAST_ID_FILE, "r") as f:
                return int(f.read().strip())
    except Exception:
        pass
    return 0


def save_state(update_id: int):
    """update_id 저장 후 GitHub 커밋"""
    with open(LAST_ID_FILE, "w") as f:
        f.write(str(update_id))

    os.system('git config user.email "action@github.com"')
    os.system('git config user.name "GitHub Action"')
    os.system(f'git add {LAST_ID_FILE}')
    os.system(f'git commit -m "bot: update state (id={update_id})"')
    os.system('git pull --rebase origin main')
    os.system('git push')


# ═════════════════════════════════════════════════════════════
# 새 메시지 가져오기
# ═════════════════════════════════════════════════════════════
def get_new_messages(last_id: int) -> list:
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
def trigger_github_actions(content: str) -> bool:
    log.info(f"🚀 GitHub Actions 트리거: {content[:60]}...")
    resp = requests.post(
        f"https://api.github.com/repos/{GH_REPO}/actions/workflows/telegram-post.yml/dispatches",
        headers={
            "Authorization": f"token {GH_PAT}",
            "Accept": "application/vnd.github.v3+json",
        },
        json={
            "ref": "main",
            "inputs": {
                "custom_content": content,
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

    last_id = get_last_update_id()
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
            save_state(update_id)
            continue

        # 내용이 너무 짧으면 안내
        if len(text) < 20:
            send_telegram(
                "✏️ 글 내용을 더 자세히 보내주세요! (최소 20자)\n\n"
                "예시:\n"
                "Netflix가 VOID라는 AI 영상편집 기술을 오픈소스로 공개했어. "
                "영상에서 물체를 지우면 물리 법칙까지 자동으로 재계산해줘."
            )
            save_state(update_id)
            continue

        # 포스팅 시작 알림
        send_telegram(
            f"✍️ 포스팅 시작!\n\n"
            f"📄 내용 미리보기:\n{text[:100]}{'...' if len(text) > 100 else ''}\n\n"
            f"⏱ 약 5~10분 후 완료 알림이 와요!"
        )

        success = trigger_github_actions(text)
        if not success:
            send_telegram("❌ 트리거 실패했어요. 잠시 후 다시 시도해주세요.")

        save_state(update_id)


if __name__ == "__main__":
    main()
