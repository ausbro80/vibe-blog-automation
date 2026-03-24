import sys
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

sys.path.insert(0, 'src')
from youtube_shorts import post_youtube_shorts

# 채널 소개 카드 이미지 (보라 그라데이션 톤)
intro_card_urls = [
    "https://placehold.co/1080x1080/6c3aed/ffffff?text=바이브코딩+스쿨",
    "https://placehold.co/1080x1080/7c3aed/ffffff?text=AI+코딩+최신+소식",
    "https://placehold.co/1080x1080/8c3aed/ffffff?text=초보자도+OK",
    "https://placehold.co/1080x1080/9c3aed/ffffff?text=매일+업데이트",
    "https://placehold.co/1080x1080/a855f7/ffffff?text=지금+구독하세요",
]

url = post_youtube_shorts(
    title="바이브코딩스쿨 채널 오픈! AI 코딩 정보 매일 공유합니다 #Shorts",
    content_html="""
    <p>안녕하세요! 바이브코딩스쿨입니다.</p>
    <p>코딩을 전혀 몰라도 AI로 앱을 만들 수 있는 시대가 왔어요.</p>
    <p>저희 채널에서는 매일 최신 AI 코딩 도구와 실전 활용법을 공유할 예정이에요.</p>
    <p>Claude, Gemini, Cursor, Lovable 등 요즘 핫한 AI 도구들을 초보자도 쉽게 따라할 수 있도록 알려드릴게요.</p>
    <p>팔로우하고 매일 업데이트 받아보세요!</p>
    """,
    blog_url="https://www.vibecodingschools.com",
    card_image_urls=intro_card_urls,
)

print("===== 결과 =====")
print("유튜브 URL:", url if url else "업로드 실패")
