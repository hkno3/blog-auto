"""
Blog Auto - Flask 메인 앱
"""
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for

from config import get_api_key, set_api_key, get_setting, set_setting
from database.db import init_db, get_posts, get_logs, add_log, get_gemini_usage
from modules.keyword_fetcher import get_fresh_keywords, _get_naver_autocomplete, _get_naver_related, _get_google_autocomplete
from modules.blogger_uploader import check_auth_status
from modules.scheduler import run_single_post, run_batch
from modules.keyword_analyzer import analyze_keywords
from modules.celebrity_fetcher import get_celebrity_keywords

app = Flask(__name__)
app.secret_key = "blog-auto-secret-2024"

# DB 초기화
init_db()


# ─── 대시보드 ──────────────────────────────────────────

@app.route("/")
def index():
    posts = get_posts(300)
    logs = get_logs(10)
    auth = check_auth_status()
    stats = {
        "total": len(posts),
        "published": sum(1 for p in posts if p["status"] == "published"),
        "failed": sum(1 for p in posts if p["status"] == "failed"),
    }
    usage_list = get_gemini_usage(days=1)
    today_usage = usage_list[0] if usage_list else {"request_count": 0, "total_tokens": 0}
    writing_style = get_setting("writing_style") or "친근하고 정보성 있는 블로그 말투"
    return render_template("index.html", posts=posts, logs=logs, auth=auth, stats=stats,
                           gemini_today=today_usage,
                           writing_style=writing_style,
                           post_interval_minutes=get_setting("post_interval_minutes") or 60,
                           image_count=get_setting("image_count") or 5,
                           min_content_length=get_setting("min_content_length") or 800)


@app.route("/api/gemini-usage")
def api_gemini_usage():
    usage = get_gemini_usage(days=7)
    return jsonify({"usage": usage})


# ─── 글 생성 (즉시 실행) ──────────────────────────────

@app.route("/run/now", methods=["POST"])
def run_now():
    data = request.json or {}
    keywords = data.get("keywords", [])
    manual = data.get("keyword", "").strip()
    if not keywords and manual:
        keywords = [manual]

    settings = {
        "image_count": int(data.get("image_count", 5)),
        "min_content_length": int(data.get("min_content_length", 800)),
        "writing_style": data.get("writing_style", ""),
    }
    count = len(keywords) or 1

    def _run():
        run_batch(keywords=keywords or None, count=count, scheduled=False, settings=settings)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    kw_str = ", ".join(keywords) if keywords else "자동"
    add_log(f"즉시 실행 요청: {count}개 ({kw_str})")
    return jsonify({"success": True, "message": f"{count}개 글 작성을 시작했습니다."})


@app.route("/run/scheduled", methods=["POST"])
def run_scheduled():
    data = request.json or {}
    keywords = data.get("keywords", [])
    interval = int(data.get("interval_minutes", 60))
    count = len(keywords) or int(data.get("count", 1))

    settings = {
        "image_count": int(data.get("image_count", 5)),
        "min_content_length": int(data.get("min_content_length", 800)),
        "writing_style": data.get("writing_style", ""),
    }

    def _run():
        run_batch(keywords=keywords or None, count=count,
                  interval_minutes=interval, scheduled=True, settings=settings)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    kw_str = ", ".join(keywords) if keywords else "자동"
    add_log(f"예약 실행 요청: {count}개 ({interval}분 간격) - {kw_str}")
    return jsonify({"success": True, "message": f"{count}개 글을 {interval}분 간격으로 예약했습니다."})


# ─── 키워드 미리보기 (기본) ────────────────────────────

@app.route("/api/keywords")
def api_keywords():
    source = request.args.get("source", "google")
    keywords = get_fresh_keywords(count=100, source=source)
    return jsonify({"keywords": keywords})


@app.route("/api/keywords/suggest")
def api_keywords_suggest():
    keyword = request.args.get("keyword", "").strip()
    if not keyword:
        return jsonify({"keywords": []})
    seen = set()
    results = [keyword]
    seen.add(keyword)
    for kw in _get_naver_autocomplete(keyword, max_count=10):
        if kw not in seen:
            results.append(kw)
            seen.add(kw)
    for kw in _get_naver_related(keyword, max_count=10):
        if kw not in seen:
            results.append(kw)
            seen.add(kw)
    for kw in _get_google_autocomplete(keyword, max_count=10):
        if kw not in seen:
            results.append(kw)
            seen.add(kw)
    return jsonify({"keywords": results})


# ─── 유명인 키워드 ────────────────────────────────────

@app.route("/api/keywords/celebrity")
def api_keywords_celebrity():
    count = int(request.args.get("count", 20))
    try:
        keywords = get_celebrity_keywords(count=count)
        return jsonify({"keywords": keywords})
    except Exception as e:
        add_log(f"유명인 키워드 수집 오류: {e}", "ERROR")
        return jsonify({"keywords": [], "error": str(e)})


# ─── 수익형 키워드 분석 ────────────────────────────────

@app.route("/api/keywords/analyze")
def api_keywords_analyze():
    mode = request.args.get("mode", "health")  # health | biz
    try:
        results = analyze_keywords(mode=mode, top_n=5)
        return jsonify({"success": True, "results": results})
    except Exception as e:
        add_log(f"키워드 분석 오류: {e}", "ERROR")
        return jsonify({"success": False, "error": str(e)})


# ─── 설정 ──────────────────────────────────────────────

@app.route("/settings")
def settings():
    config = {
        "gemini_key": "****" if get_api_key("gemini") else "",
        "unsplash_key": "****" if get_api_key("unsplash") else "",
        "pexels_key": "****" if get_api_key("pexels") else "",
        "pixabay_key": "****" if get_api_key("pixabay") else "",
        "naver_ad_customer_id": get_api_key("naver_ad_customer_id") or "",
        "naver_ad_license": "****" if get_api_key("naver_ad_license") else "",
        "naver_ad_secret": "****" if get_api_key("naver_ad_secret") else "",
        "naver_client_id": get_api_key("naver_client_id") or "",
        "naver_client_secret": "****" if get_api_key("naver_client_secret") else "",
        "google_sheets_key": "****" if get_api_key("google_sheets") else "",
        "blogger_blog_id": get_setting("blogger_blog_id") or "",
        "keyword_source": get_setting("keyword_source") or "google",
        "batch_count": get_setting("batch_count") or 3,
        "post_interval_minutes": get_setting("post_interval_minutes") or 60,
        "image_count": get_setting("image_count") or 5,
        "min_content_length": get_setting("min_content_length") or 800,
        "writing_style": get_setting("writing_style") or "친근하고 정보성 있는 블로그 말투",
    }
    auth = check_auth_status()
    return render_template("settings.html", config=config, auth=auth)


@app.route("/settings/save", methods=["POST"])
def settings_save():
    data = request.json or {}

    # API 키 저장 (빈 값이면 기존 유지)
    api_keys = {
        "gemini": data.get("gemini_key", ""),
        "unsplash": data.get("unsplash_key", ""),
        "pexels": data.get("pexels_key", ""),
        "pixabay": data.get("pixabay_key", ""),
        "naver_ad_customer_id": data.get("naver_ad_customer_id", ""),
        "naver_ad_license": data.get("naver_ad_license", ""),
        "naver_ad_secret": data.get("naver_ad_secret", ""),
        "naver_client_id": data.get("naver_client_id", ""),
        "naver_client_secret": data.get("naver_client_secret", ""),
        "google_sheets": data.get("google_sheets_key", ""),
    }
    for name, value in api_keys.items():
        if value and value != "****":
            set_api_key(name, value)

    # 일반 설정 저장
    settings_map = {
        "blogger_blog_id": data.get("blogger_blog_id"),
        "keyword_source": data.get("keyword_source"),
        "batch_count": data.get("batch_count"),
        "post_interval_minutes": data.get("post_interval_minutes"),
        "image_count": data.get("image_count"),
        "min_content_length": data.get("min_content_length"),
        "writing_style": data.get("writing_style"),
    }
    for name, value in settings_map.items():
        if value is not None:
            set_setting(name, value)

    add_log("설정 저장 완료")
    return jsonify({"success": True})


@app.route("/settings/test-api", methods=["POST"])
def test_api():
    """API 키 연결 테스트"""
    data = request.json or {}
    api_name = data.get("api")
    results = {}

    if api_name in ("gemini", "all"):
        try:
            from google import genai
            key = get_api_key("gemini")
            if key:
                client = genai.Client(api_key=key)
                client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents="테스트",
                )
                results["gemini"] = {"ok": True, "msg": "연결 성공"}
            else:
                results["gemini"] = {"ok": False, "msg": "API 키 없음"}
        except Exception as e:
            results["gemini"] = {"ok": False, "msg": str(e)}

    if api_name in ("blogger", "all"):
        auth = check_auth_status()
        results["blogger"] = {
            "ok": auth["authenticated"],
            "msg": auth.get("blog_name", "") or auth.get("error", "인증 실패"),
        }

    if api_name in ("unsplash", "all"):
        try:
            import requests as req
            key = get_api_key("unsplash")
            if key:
                r = req.get(
                    "https://api.unsplash.com/search/photos",
                    params={"query": "test", "per_page": 1},
                    headers={"Authorization": f"Client-ID {key}"},
                    timeout=5,
                )
                r.raise_for_status()
                results["unsplash"] = {"ok": True, "msg": "연결 성공"}
            else:
                results["unsplash"] = {"ok": False, "msg": "API 키 없음"}
        except Exception as e:
            results["unsplash"] = {"ok": False, "msg": str(e)}

    if api_name in ("pexels", "all"):
        try:
            import requests as req
            key = get_api_key("pexels")
            if key:
                r = req.get(
                    "https://api.pexels.com/v1/search",
                    params={"query": "test", "per_page": 1},
                    headers={"Authorization": key},
                    timeout=5,
                )
                r.raise_for_status()
                results["pexels"] = {"ok": True, "msg": "연결 성공"}
            else:
                results["pexels"] = {"ok": False, "msg": "API 키 없음"}
        except Exception as e:
            results["pexels"] = {"ok": False, "msg": str(e)}

    if api_name in ("pixabay", "all"):
        try:
            import requests as req
            key = get_api_key("pixabay")
            if key:
                r = req.get(
                    "https://pixabay.com/api/",
                    params={"key": key, "q": "test", "per_page": 3},
                    timeout=5,
                )
                r.raise_for_status()
                data_r = r.json()
                count = data_r.get("totalHits", 0)
                results["pixabay"] = {"ok": True, "msg": f"연결 성공 (총 {count}개 이미지)"}
            else:
                results["pixabay"] = {"ok": False, "msg": "API 키 없음"}
        except Exception as e:
            results["pixabay"] = {"ok": False, "msg": str(e)}

    if api_name in ("naver", "all"):
        try:
            import requests as req
            client_id = get_api_key("naver_client_id")
            client_secret = get_api_key("naver_client_secret")
            if client_id and client_secret:
                r = req.get(
                    "https://openapi.naver.com/v1/search/news.json",
                    headers={
                        "X-Naver-Client-Id": client_id,
                        "X-Naver-Client-Secret": client_secret,
                    },
                    params={"query": "테스트", "display": 1},
                    timeout=5,
                )
                r.raise_for_status()
                total = r.json().get("total", 0)
                results["naver"] = {"ok": True, "msg": f"연결 성공 (검색결과 {total:,}건)"}
            else:
                results["naver"] = {"ok": False, "msg": "Client ID 또는 Secret 없음"}
        except Exception as e:
            results["naver"] = {"ok": False, "msg": str(e)}

    if api_name in ("google_sheets", "all"):
        try:
            import requests as req
            key = get_api_key("google_sheets")
            if key:
                # bizachieve 첫 번째 시트로 테스트
                test_id = "1F5OMpIyI1ZM8V39Zt4-ls_TzBqvWr0N5Tim_td_KwxA"
                r = req.get(
                    f"https://sheets.googleapis.com/v4/spreadsheets/{test_id}/values/A1:A3",
                    params={"key": key},
                    timeout=10,
                )
                r.raise_for_status()
                data_r = r.json()
                count = len(data_r.get("values", []))
                results["google_sheets"] = {"ok": True, "msg": f"연결 성공 ({count}개 행 확인)"}
            else:
                results["google_sheets"] = {"ok": False, "msg": "API 키 없음"}
        except Exception as e:
            results["google_sheets"] = {"ok": False, "msg": str(e)}

    return jsonify(results)


# ─── 로그 ──────────────────────────────────────────────

@app.route("/logs")
def logs_page():
    logs = get_logs(200)
    return render_template("logs.html", logs=logs)


@app.route("/api/logs")
def api_logs():
    logs = get_logs(50)
    return jsonify({"logs": logs})


@app.route("/api/posts")
def api_posts():
    posts = get_posts(50)
    return jsonify({"posts": posts})


# ─── Blogger OAuth 인증 시작 ───────────────────────────

@app.route("/auth/blogger")
def auth_blogger():
    try:
        from modules.blogger_uploader import get_blogger_service
        get_blogger_service()
        add_log("Blogger OAuth 인증 완료")
        return redirect(url_for("settings") + "?auth=success")
    except Exception as e:
        add_log(f"Blogger 인증 실패: {e}", "ERROR")
        return redirect(url_for("settings") + f"?auth=error&msg={str(e)}")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
