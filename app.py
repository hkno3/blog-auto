"""
Blog Auto - Flask 메인 앱
"""
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for

from config import get_api_key, set_api_key, get_setting, set_setting
from database.db import init_db, get_posts, get_logs, add_log
from modules.keyword_fetcher import get_fresh_keywords
from modules.blogger_uploader import check_auth_status
from modules.scheduler import run_single_post, run_batch
from modules.keyword_analyzer import analyze_keywords

app = Flask(__name__)
app.secret_key = "blog-auto-secret-2024"

# DB 초기화
init_db()


# ─── 대시보드 ──────────────────────────────────────────

@app.route("/")
def index():
    posts = get_posts(20)
    logs = get_logs(10)
    auth = check_auth_status()
    stats = {
        "total": len(get_posts(1000)),
        "published": sum(1 for p in get_posts(1000) if p["status"] == "published"),
        "failed": sum(1 for p in get_posts(1000) if p["status"] == "failed"),
    }
    return render_template("index.html", posts=posts, logs=logs, auth=auth, stats=stats)


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
    keywords = get_fresh_keywords(count=10, source=source)
    return jsonify({"keywords": keywords})


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
        "naver_ad_customer_id": get_api_key("naver_ad_customer_id") or "",
        "naver_ad_license": "****" if get_api_key("naver_ad_license") else "",
        "naver_ad_secret": "****" if get_api_key("naver_ad_secret") else "",
        "naver_client_id": get_api_key("naver_client_id") or "",
        "naver_client_secret": "****" if get_api_key("naver_client_secret") else "",
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
        "naver_ad_customer_id": data.get("naver_ad_customer_id", ""),
        "naver_ad_license": data.get("naver_ad_license", ""),
        "naver_ad_secret": data.get("naver_ad_secret", ""),
        "naver_client_id": data.get("naver_client_id", ""),
        "naver_client_secret": data.get("naver_client_secret", ""),
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
