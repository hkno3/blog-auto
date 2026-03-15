# Blog Auto - Blogspot 자동 글쓰기 프로그램

## 기능
- 실시간 이슈 키워드 자동 검색 (Google Trends / 네이버 뉴스)
- Gemini AI SEO 최적화 글쓰기
- 이미지 자동 삽입 (Unsplash / Pexels)
- 외부 링크 자동 삽입 (bodyandwell.com / bizachieve.com)
- Blogspot 자동 업로드 / 예약 발행
- 중복 키워드 방지 DB
- 웹 대시보드 (실행, 설정, 로그)

## 설치

```bash
pip install -r requirements.txt
python app.py
```

브라우저에서 http://localhost:5000 접속

## 필수 설정

### 1. Gemini API 키 (무료)
https://aistudio.google.com/app/apikey 에서 발급 후 설정 화면에 입력

### 2. Blogger 연동
1. https://console.cloud.google.com 에서 프로젝트 생성
2. Blogger API v3 활성화
3. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
4. credentials.json 다운로드 → 프로젝트 루트에 저장
5. 설정 화면 → "Google 계정으로 인증하기" 클릭

### 3. 이미지 API (선택, 무료)
- Unsplash: https://unsplash.com/developers
- Pexels: https://www.pexels.com/api/
