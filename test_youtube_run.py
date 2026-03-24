import sys
sys.path.insert(0, 'src')
from youtube_shorts import post_youtube_shorts

url = post_youtube_shorts(
    title="바이브코딩 스쿨 테스트 쇼츠",
    content_html="<p>안녕하세요! 바이브코딩 스쿨입니다. 코딩 몰라도 AI로 앱을 만들 수 있어요. 매일 최신 AI 코딩 정보를 업데이트하고 있으니 구독하고 놓치지 마세요!</p>",
    image_url="https://placehold.co/1200x630/6366f1/ffffff?text=Vibe+Coding+School",
    blog_url="https://www.vibecodingschools.com"
)
print("===== 결과 =====")
print("유튜브 URL:", url if url else "업로드 실패")
