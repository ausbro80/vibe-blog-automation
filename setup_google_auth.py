"""
Google OAuth 초기 설정 스크립트
────────────────────────────────
최초 1회만 로컬에서 실행하세요.
생성된 JSON을 GitHub Secrets에 GOOGLE_CREDENTIALS_JSON으로 등록하면 됩니다.
실행 방법:
  pip install google-auth-oauthlib
  python setup_google_auth.py
"""
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Blogger + YouTube + Cloud TTS 권한
SCOPES = [
    "https://www.googleapis.com/auth/blogger",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/cloud-platform",  # ← Cloud TTS 추가
]

def main():
    print("=" * 55)
    print("  Google Blogger + YouTube + Cloud TTS OAuth 인증 설정")
    print("=" * 55)
    print()
    print("📋 사전 준비:")
    print("  1. https://console.cloud.google.com 접속")
    print("  2. 기존 프로젝트 선택")
    print("  3. 아래 API 활성화 확인:")
    print("     - Blogger API ✅ (이미 됨)")
    print("     - YouTube Data API v3 ✅ (이미 됨)")
    print("     - Cloud Text-to-Speech API ← 새로 추가 필요!")
    print("       https://console.cloud.google.com/apis/library/texttospeech.googleapis.com")
    print("  4. 기존 client_secret.json 그대로 사용 가능")
    print()
    print("⚠️  브라우저에서 인증 시 유튜브 채널 계정으로 로그인!")
    print()

    client_secret_file = input("client_secret.json 파일 경로 (엔터 = 현재 폴더): ").strip()
    if not client_secret_file:
        client_secret_file = "client_secret.json"

    try:
        flow = InstalledAppFlow.from_client_secrets_file(client_secret_file, SCOPES)
        creds = flow.run_local_server(port=0)
    except FileNotFoundError:
        print(f"\n❌ 파일을 찾을 수 없어요: {client_secret_file}")
        print("   Google Cloud Console에서 JSON을 다운로드했는지 확인하세요.")
        return

    credentials_json = json.dumps({
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
    })

    print()
    print("✅ 인증 완료! (Blogger + YouTube + Cloud TTS 권한 포함)")
    print()
    print("━" * 55)
    print("📋 아래 JSON을 복사해서 GitHub Secrets에 등록하세요")
    print("   Secret 이름: GOOGLE_CREDENTIALS_JSON")
    print("   (기존 값 덮어쓰기)")
    print("━" * 55)
    print(credentials_json)
    print("━" * 55)
    print()

    with open("google_credentials.json", "w") as f:
        f.write(credentials_json)
    print("💾 google_credentials.json 파일로도 저장되었습니다.")
    print("   ⚠️  이 파일은 절대 GitHub에 올리지 마세요!")

if __name__ == "__main__":
    main()
