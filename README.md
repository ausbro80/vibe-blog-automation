# 🤖 Vibe Coding Blog 자동화 시스템

> 매일 자동으로 최신 AI 코딩 뉴스를 수집하고, 교육용 블로그 글을 작성해 Google Blogger에 포스팅합니다.

---

## ✨ 기능

| 기능 | 설명 |
|------|------|
| 📡 **뉴스 자동 수집** | Claude 웹서치로 매일 최신 vibe coding 트렌드 수집 |
| ✍️ **AI 글 작성** | Claude Sonnet 4으로 초보자 교육용 2,500자+ 글 생성 |
| 🔍 **SEO 최적화** | 클릭률 높은 제목 5개 후보 생성 → 최적 선택 |
| 🎨 **썸네일 생성** | DALL-E 3으로 주제별 16:9 이미지 자동 생성 |
| 📤 **자동 포스팅** | Google Blogger API로 태그·메타태그 포함 포스팅 |
| ⏰ **일일 자동 실행** | GitHub Actions cron으로 매일 오전 9시(KST) 실행 |

---

## 🗂️ 프로젝트 구조

```
vibe-blog-automation/
├── .github/
│   └── workflows/
│       └── daily-post.yml      # GitHub Actions 스케줄러
├── src/
│   └── main.py                 # 메인 자동화 스크립트
├── setup_google_auth.py        # Google OAuth 최초 설정 (로컬 1회 실행)
├── requirements.txt
├── .gitignore
└── README.md
```

---

## 🚀 설정 가이드 (최초 1회)

### 1단계 — API 키 준비

#### A. Anthropic API 키
1. https://console.anthropic.com 접속
2. API Keys → Create Key
3. 키 복사해서 보관

#### B. OpenAI API 키 (DALL-E 3용)
1. https://platform.openai.com 접속
2. API Keys → Create new secret key
3. 키 복사

#### C. Google Blogger 설정
1. https://console.cloud.google.com 접속
2. 새 프로젝트 생성
3. **APIs & Services → Library** 검색창에 "Blogger API v3" → 사용 설정
4. **APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID**
   - 유형: **Desktop app**
   - 이름: vibe-blog-automation
5. JSON 다운로드 → `client_secret.json`으로 저장

#### D. Blogger Blog ID 확인
1. https://blogger.com → 블로그 대시보드
2. URL에서 `blogID=XXXXXXXXXXXXXXX` 부분이 Blog ID

---

### 2단계 — Google OAuth 인증 (로컬에서 1회 실행)

```bash
# 의존성 설치
pip install google-auth-oauthlib

# OAuth 인증 스크립트 실행
python setup_google_auth.py
```

→ 브라우저가 열리면 Google 계정으로 로그인하고 권한 허용  
→ 터미널에 출력된 JSON을 복사해두기

---

### 3단계 — GitHub 저장소 설정

```bash
# 저장소 생성 (GitHub에서 private repo 권장)
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/vibe-blog-automation.git
git push -u origin main
```

---

### 4단계 — GitHub Secrets 등록

GitHub 저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| Secret 이름 | 값 |
|------------|-----|
| `ANTHROPIC_API_KEY` | Anthropic API 키 |
| `OPENAI_API_KEY` | OpenAI API 키 |
| `BLOGGER_BLOG_ID` | Blogger Blog ID (숫자) |
| `GOOGLE_CREDENTIALS_JSON` | setup_google_auth.py 실행 후 출력된 JSON 전체 |

---

### 5단계 — 테스트 실행

GitHub 저장소 → **Actions → 🤖 Vibe Coding Blog 자동 포스팅 → Run workflow**  
→ `dry_run` 체크 해제 → Run 클릭

---

## ⏰ 자동 실행 스케줄

```yaml
# .github/workflows/daily-post.yml
cron: "0 0 * * *"   # UTC 00:00 = KST 09:00 매일
```

시간 변경하려면 https://crontab.guru 에서 cron 표현식 생성

---

## 💰 예상 비용

| 서비스 | 매일 1포스트 기준 | 월 비용(약) |
|--------|-------------------|------------|
| Claude API (Sonnet 4) | 약 $0.03/포스트 | ~$1 |
| OpenAI DALL-E 3 | 약 $0.04/이미지 | ~$1.2 |
| GitHub Actions | 무료 (월 2,000분) | $0 |
| Google Blogger | 무료 | $0 |
| **합계** | | **~$2.2/월** |

---

## 🔧 커스터마이징

### 검색 주제 변경 (`src/main.py` 내 `collect_latest_news()`)

```python
search_topics = [
    "vibe coding 최신 뉴스 2025",
    "Claude Code AI 코딩 도구 업데이트",
    # 원하는 주제 추가/변경
    "Replit AI 업데이트",
    "노코드 앱 개발 트렌드",
]
```

### 포스팅 시간 변경 (`.github/workflows/daily-post.yml`)

```yaml
# 오전 7시(KST) = UTC 22:00 전날
cron: "0 22 * * *"
```

---

## ❓ 자주 묻는 문제

**Q. 이미지가 안 나와요**  
A. OpenAI 계정에 크레딧이 있는지 확인. 없으면 Unsplash 무료 API로 대체 가능.

**Q. Blogger 포스팅이 403 오류 나요**  
A. `setup_google_auth.py`를 다시 실행해서 Google Credentials를 갱신하세요.

**Q. 매일 같은 주제의 글이 나와요**  
A. `search_topics` 배열을 더 다양하게 구성하거나, 날짜 기반으로 주제를 순환하도록 수정하세요.

---

## 📄 라이선스

MIT License — 자유롭게 사용, 수정, 배포 가능
