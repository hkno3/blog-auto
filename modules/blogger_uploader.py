"""
Blogger 업로드 모듈 - Google OAuth2
"""
import os
import json
from pathlib import Path
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

from config import get_api_key, get_setting
from database.db import add_log

SCOPES = ["https://www.googleapis.com/auth/blogger"]
TOKEN_FILE = Path(__file__).parent.parent / "token.json"
CREDENTIALS_FILE = Path(__file__).parent.parent / "credentials.json"


def _get_credentials() -> Credentials:
    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                add_log("Google OAuth 토큰 자동 갱신 완료")
            except Exception as e:
                add_log(f"토큰 갱신 실패 - 재인증 필요: {e}", "ERROR")
                creds = None

        if not creds:
            if not CREDENTIALS_FILE.exists():
                raise FileNotFoundError(
                    "credentials.json 파일이 없습니다. "
                    "Google Cloud Console에서 OAuth 클라이언트 자격증명을 다운로드하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())

    return creds


def get_blogger_service():
    creds = _get_credentials()
    return build("blogger", "v3", credentials=creds)


def get_blog_id(service) -> str:
    """설정된 Blog ID 반환 또는 자동 검색"""
    blog_id = get_setting("blogger_blog_id")
    if blog_id:
        return blog_id

    blogs = service.blogs().listByUser(userId="self").execute()
    items = blogs.get("items", [])
    if not items:
        raise ValueError("연결된 Blogger 블로그가 없습니다.")
    return items[0]["id"]


def publish_post(
    title: str,
    content: str,
    tags: list[str] = None,
    scheduled_at: str = None,
    is_draft: bool = False,
) -> dict:
    """
    Blogger에 글 발행
    scheduled_at: ISO 8601 형식 (예: "2024-01-01T09:00:00+09:00")
    반환: {id, url, status}
    """
    add_log(f"Blogger 업로드 시작: {title}")
    try:
        service = get_blogger_service()
        blog_id = get_blog_id(service)

        body = {
            "kind": "blogger#post",
            "title": title,
            "content": content,
        }
        if tags:
            body["labels"] = tags

        if scheduled_at:
            body["published"] = scheduled_at

        is_draft_mode = is_draft or bool(scheduled_at)
        result = service.posts().insert(
            blogId=blog_id,
            body=body,
            isDraft=is_draft_mode,
        ).execute()

        post_id = result.get("id")
        post_url = result.get("url", "")
        add_log(f"Blogger 업로드 완료: {post_url}")
        return {"id": post_id, "url": post_url, "status": result.get("status")}

    except Exception as e:
        add_log(f"Blogger 업로드 실패: {e}", "ERROR")
        raise


def check_auth_status() -> dict:
    """인증 상태 확인"""
    try:
        service = get_blogger_service()
        blog_id = get_blog_id(service)
        blog = service.blogs().get(blogId=blog_id).execute()
        return {
            "authenticated": True,
            "blog_name": blog.get("name", ""),
            "blog_url": blog.get("url", ""),
            "blog_id": blog_id,
        }
    except FileNotFoundError as e:
        return {"authenticated": False, "error": str(e)}
    except Exception as e:
        return {"authenticated": False, "error": str(e)}
