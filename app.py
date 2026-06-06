# server
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template
import requests
import json
import re
import time
import threading
from dotenv import load_dotenv
import os

from url_utils import (
    normalize_url,
    paper_link,
    normalize_email,
    is_reachable,
    validated_faculty_url,
)

load_dotenv()
API_KEY = os.getenv("HACKCLUB_API_KEY")
SCHOLAR_API_KEY = os.getenv("SEMANTIC_SCHOLAR_API_KEY")
app = Flask(__name__)

_SCHOLAR_CACHE = {}
_scholar_lock = threading.Lock()

SCHOLAR_RATE_LIMIT_MSG = (
    "Publications could not be loaded — Semantic Scholar's API rate limit was reached. "
    "Wait a minute and try again."
)
SCHOLAR_UNAVAILABLE_MSG = (
    "Publications could not be loaded — the publication service is temporarily unavailable. "
    "Try again later."
)
AI_RATE_LIMIT_MSG = (
    "AI API rate limit reached. Please wait a minute and try again."
)
AI_TIMEOUT_MSG = (
    "AI request timed out. Try fewer research areas or search again in a moment."
)
AI_TOKEN_LIMIT_MSG = (
    "AI response was cut off (token limit). Try fewer research areas or a shorter search."
)
AI_UNAVAILABLE_MSG = (
    "AI service is temporarily unavailable. Please try again in a moment."
)


def _remove_think_blocks(text):
    open_tag = "<" + "think" + ">"
    close_tag = "<" + "/" + "think" + ">"
    lower = text.lower()
    while open_tag in lower:
        start = lower.find(open_tag)
        end = lower.find(close_tag, start)
        if end == -1:
            break
        text = text[:start] + text[end + len(close_tag) :]
        lower = text.lower()
    return text


def _strip_llm_wrapper(raw_text):
    text = _remove_think_blocks((raw_text or "").strip())
    fence = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return text.strip()


def _repair_truncated_json(text):
    text = text.strip()
    text = re.sub(r',\s*"[^"]*":\s*"?[^"{}[\]]*$', "", text)
    text = re.sub(r',\s*\{[^}]*$', "", text)
    text = re.sub(r",\s*$", "", text)
    text += "]" * max(0, text.count("[") - text.count("]"))
    text += "}" * max(0, text.count("{") - text.count("}"))
    return text


def _parse_llm_json(raw_text):
    text = _strip_llm_wrapper(raw_text)
    attempts = [text]
    obj_start = text.find("{")
    arr_start = text.find("[")
    starts = [i for i in (obj_start, arr_start) if i != -1]
    if starts:
        attempts.append(text[min(starts) :])
    last_error = None
    for candidate in attempts:
        for variant in (candidate, _repair_truncated_json(candidate)):
            try:
                return json.loads(variant)
            except json.JSONDecodeError as exc:
                last_error = exc
    raise last_error or json.JSONDecodeError("No JSON found", raw_text or "", 0)


def _extract_professors(parsed):
    if isinstance(parsed, list):
        return parsed
    if not isinstance(parsed, dict):
        return []
    if "professors" in parsed and isinstance(parsed["professors"], list):
        return parsed["professors"]
    for key, value in parsed.items():
        if "prof" in key.lower() and isinstance(value, list):
            return value
    return []


def _coerce_topics(prof):
    topics = prof.get("topics")
    if isinstance(topics, list):
        return topics
    if isinstance(topics, str) and topics.strip():
        return [topics.strip()]
    for key in ("research_areas", "areas", "area", "fields"):
        value = prof.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [value.strip()]
    return []


def _sanitize_professor(prof):
    if not isinstance(prof, dict):
        return None
    name = (prof.get("name") or "").strip()
    if not name:
        return None
    role = (prof.get("role") or "").lower()
    if "emeritus" in role:
        return None
    summary = (
        prof.get("research_summary")
        or prof.get("summary")
        or prof.get("bio")
        or prof.get("area")
        or ""
    )
    if isinstance(summary, list):
        summary = "; ".join(str(item) for item in summary)
    profile_url = prof.get("profile_url") or prof.get("url") or prof.get("profile")
    return {
        **prof,
        "name": name,
        "role": prof.get("role") or "",
        "department": prof.get("department") or "",
        "topics": _coerce_topics(prof),
        "research_summary": str(summary).strip(),
        "email": normalize_email(prof.get("email")),
        "profile_url": normalize_url(profile_url),
    }


_CATEGORY_EXPANSIONS = {
    "ml": ("machine learning", "deep learning"),
    "ai": ("artificial intelligence",),
    "tech": ("technology", "technological", "engineering"),
    "neuro": ("neuroscience", "neural", "brain"),
    "hci": ("human-computer interaction", "human computer interaction"),
    "psych": ("psychology", "psych"),
    "cs": ("computer science",),
}


def _parse_categories(category):
    return [part.strip() for part in category.split(",") if part.strip()]


def _category_search_terms(term):
    normalized = term.strip().lower()
    if not normalized:
        return []
    terms = {normalized}
    terms.update(_CATEGORY_EXPANSIONS.get(normalized, ()))
    if " " in normalized:
        terms.add(normalized.replace(" ", "-"))
        terms.add(normalized.replace(" ", ""))
    if "neuro" in normalized:
        terms.update(("neuroscience", "neuro", "neural", "brain"))
    if "technolog" in normalized or normalized == "tech":
        terms.update(("technology", "technological", "tech"))
    if "learn" in normalized:
        terms.update(("machine learning", "deep learning", "ml"))
    return terms


def _professor_haystack(prof):
    parts = [
        prof.get("role", ""),
        prof.get("department", ""),
        prof.get("research_summary", ""),
        " ".join(prof.get("topics") or []),
    ]
    return " ".join(parts).lower()


def _count_category_matches(prof, categories):
    if not categories:
        return 0
    haystack = _professor_haystack(prof)
    matched = 0
    for category in categories:
        if any(term in haystack for term in _category_search_terms(category)):
            matched += 1
    return matched


def _matched_categories(prof, categories):
    haystack = _professor_haystack(prof)
    matched = []
    for category in categories:
        if any(term in haystack for term in _category_search_terms(category)):
            matched.append(category)
    return matched


def _empty_scholar_data(warning=None):
    return {
        "paper_count": 0,
        "latest_year": None,
        "scholar_url": None,
        "papers": [],
        "warning": warning,
    }


def _scholar_error_message(status_code):
    if status_code == 429:
        return SCHOLAR_RATE_LIMIT_MSG
    if status_code >= 500:
        return SCHOLAR_UNAVAILABLE_MSG
    return "Could not load publications for this professor right now."


def _ai_error_message(exc, response=None):
    status = getattr(response, "status_code", None)
    body_text = ""
    if response is not None:
        try:
            body = response.json()
            body_text = (
                body.get("message")
                or (body.get("error") or {}).get("message")
                or body.get("error")
                or ""
            )
            if isinstance(body_text, dict):
                body_text = body_text.get("message", "")
        except (ValueError, AttributeError, TypeError):
            body_text = response.text or ""

    combined = f"{exc} {body_text}".lower()
    if status == 429 or "rate limit" in combined or "too many requests" in combined:
        return AI_RATE_LIMIT_MSG
    if status == 504 or "timeout" in combined or "timed out" in combined:
        return AI_TIMEOUT_MSG
    if "token" in combined or "maximum context" in combined or "too long" in combined:
        return AI_TOKEN_LIMIT_MSG
    if status in (502, 503) or "unavailable" in combined:
        return AI_UNAVAILABLE_MSG
    if status:
        return f"AI service error ({status}). Please try again in a moment."
    return AI_UNAVAILABLE_MSG


def _search_warnings(professors):
    warnings = []
    scholar_issues = [p for p in professors if p.get("publications_warning")]
    if not scholar_issues:
        return warnings

    all_missing = all(not p.get("publications") for p in professors)
    if all_missing:
        warnings.append(scholar_issues[0]["publications_warning"])
    else:
        warnings.append(
            "Some professors are missing publications because Semantic Scholar's "
            "API rate limit was reached. Wait a minute and search again for full results."
        )
    return warnings


def _fetch_professors_from_ai(school, category):
    last_error = None
    for attempt in range(2):
        try:
            response = requests.post(
                "https://ai.hackclub.com/proxy/v1/chat/completions",
                headers={
                    "Authorization": "Bearer " + API_KEY,
                    "Content-Type": "application/json",
                },
                json={
                    "model": "qwen/qwen3-32b",
                    "max_tokens": 4096,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You are a research assistant. Always respond with raw JSON only. "
                                "No explanation, no markdown, no backticks, no thinking tags. "
                                "Use exactly this schema: "
                                '{"professors":[{"name":"","role":"","department":"","topics":[],"research_summary":"","email":null,"profile_url":null}]}'
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"""List professors at {school} related to any of these research areas: {category}.

                    Rules
                    - The areas are comma-separated. A professor does NOT need to match all of them — include anyone who matches at least one area.
                    - Order your list with professors who match the most areas first, then those who match fewer.
                    - Include professors who match only one area too, as long as they are a reasonable fit.
                    - Do NOT include emeritus professors
                    - Only include professors who have published research or had an active lab in the last 10 years
                    - Do NOT include anyone who is publicly known to not accept high school students or interns
                    - If you are unsure whether someone accepts high schoolers, include them
                    - Interpret typos in the research areas generously (e.g. "neurosicence" means neuroscience, "ML" means machine learning)

                    Return a JSON object with a 'professors' key containing a list. Each professor must use these exact keys: name, role, department, topics (list), research_summary, email (or null if unknown), profile_url (full https URL to their official university faculty page only — use null if you are not certain the exact page exists).""",
                        },
                    ],
                },
                timeout=120,
            )
            response.raise_for_status()
            api_data = response.json()
            raw_text = api_data["choices"][0]["message"]["content"]
            print(f"RAW RESPONSE (attempt {attempt + 1}):", raw_text)
            parsed = _parse_llm_json(raw_text)
            return _extract_professors(parsed)
        except requests.RequestException as exc:
            last_error = exc
            print(f"SEARCH API ERROR (attempt {attempt + 1}):", exc)
            if attempt == 0:
                time.sleep(2)
        except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
            last_error = exc
            print(f"SEARCH PARSE ERROR (attempt {attempt + 1}):", exc)
    raise last_error


def _pick_best_author(results, name):
    if not results:
        return None
    target = name.lower().strip()
    parts = target.split()

    def score(author):
        author_name = author.get("name", "").lower()
        if author_name == target:
            name_score = 100
        elif all(part in author_name for part in parts):
            name_score = 80
        elif target in author_name or author_name in target:
            name_score = 50
        else:
            name_score = 0
        return name_score + (author.get("paperCount") or 0) * 0.01

    return max(results, key=score)


def _scholar_headers():
    headers = {}
    if SCHOLAR_API_KEY:
        headers["x-api-key"] = SCHOLAR_API_KEY
    return headers


def _scholar_get(url, params=None, retries=3):
    for attempt in range(retries):
        response = requests.get(
            url, params=params, headers=_scholar_headers(), timeout=15
        )
        if response.status_code == 429 and attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
            continue
        return response
    return response


def _papers_from_author(author):
    raw_papers = author.get("papers") or []
    raw_papers.sort(key=lambda p: p.get("year") or 0, reverse=True)
    papers = []
    for paper in raw_papers[:15]:
        papers.append({
            "title": paper.get("title"),
            "year": paper.get("year"),
            "link": paper_link(paper),
        })
    return papers


def _fetch_scholar_data(name):
    cache_key = name.lower().strip()
    if cache_key in _SCHOLAR_CACHE:
        return _SCHOLAR_CACHE[cache_key].copy()

    if not name.strip():
        return _empty_scholar_data()

    with _scholar_lock:
        if cache_key in _SCHOLAR_CACHE:
            return _SCHOLAR_CACHE[cache_key].copy()
        time.sleep(0.35)

        warning = None
        try:
            response = _scholar_get(
                "https://api.semanticscholar.org/graph/v1/author/search",
                params={
                    "query": name,
                    "limit": 10,
                    "fields": (
                        "name,paperCount,authorId,"
                        "papers.paperId,papers.title,papers.year,"
                        "papers.externalIds,papers.openAccessPdf"
                    ),
                },
            )
            if response.status_code != 200:
                print(f"SCHOLAR ERROR for {name}: {response.status_code}")
                warning = _scholar_error_message(response.status_code)
                data = _empty_scholar_data(warning)
                _SCHOLAR_CACHE[cache_key] = data
                return data.copy()

            results = response.json().get("data", [])
            author = _pick_best_author(results, name)
            if not author:
                data = _empty_scholar_data()
                _SCHOLAR_CACHE[cache_key] = data
                return data.copy()

            papers = _papers_from_author(author)
            author_id = author.get("authorId")

            if not papers and author_id:
                detail = _scholar_get(
                    f"https://api.semanticscholar.org/graph/v1/author/{author_id}",
                    params={
                        "fields": (
                            "papers.paperId,papers.title,papers.year,"
                            "papers.externalIds,papers.openAccessPdf"
                        ),
                    },
                )
                if detail.status_code == 200:
                    papers = _papers_from_author(detail.json())
                elif detail.status_code != 200:
                    warning = _scholar_error_message(detail.status_code)

            years = [paper.get("year") for paper in papers if paper.get("year")]
            data = {
                "paper_count": author.get("paperCount") or len(papers),
                "latest_year": max(years) if years else None,
                "scholar_url": (
                    f"https://www.semanticscholar.org/author/{author_id}"
                    if author_id
                    else None
                ),
                "papers": papers,
                "warning": warning if not papers else None,
            }
            _SCHOLAR_CACHE[cache_key] = data
            return data.copy()
        except requests.RequestException as exc:
            print(f"SCHOLAR ERROR for {name}:", exc)
            response = getattr(exc, "response", None)
            status = getattr(response, "status_code", None)
            warning = _scholar_error_message(status) if status else SCHOLAR_UNAVAILABLE_MSG
            data = _empty_scholar_data(warning)
            _SCHOLAR_CACHE[cache_key] = data
            return data.copy()


def _compute_info_score(prof, scholar):
    score = 0
    if prof.get("email"):
        score += 25
    if prof.get("profile_url"):
        score += 25
    elif scholar.get("scholar_url"):
        score += 12

    role = (prof.get("role") or "").lower()
    if any(word in role for word in ("lab", "director", "head", "chair")):
        score += 15
    elif role and role not in ("professor", "faculty"):
        score += 10
    elif role:
        score += 5

    if prof.get("department"):
        score += 5
    if (prof.get("research_summary") or "").strip():
        score += 5

    topics = prof.get("topics") or []
    score += min(len(topics) * 2, 10)

    paper_count = scholar.get("paper_count") or 0
    score += min(paper_count, 15)

    latest_year = scholar.get("latest_year") or 0
    if latest_year >= 2023:
        score += 12
    elif latest_year >= 2020:
        score += 8
    elif latest_year >= 2015:
        score += 4

    return score


def _enrich_professor(prof, categories=None):
    profile_candidate = prof.get("profile_url")
    prof["profile_url"] = validated_faculty_url(profile_candidate)
    scholar = _fetch_scholar_data(prof.get("name", ""))
    prof["scholar_url"] = scholar.get("scholar_url")
    prof["publication_count"] = scholar.get("paper_count", 0)
    prof["latest_publication_year"] = scholar.get("latest_year")
    prof["publications"] = scholar.get("papers", [])
    prof["publications_warning"] = scholar.get("warning")
    prof["info_score"] = _compute_info_score(prof, scholar)
    categories = categories or []
    prof["category_match_count"] = _count_category_matches(prof, categories)
    prof["matched_areas"] = _matched_categories(prof, categories)
    return prof


def _enrich_and_rank_professors(professors, categories=None):
    if not professors:
        return []
    categories = categories or []
    enriched = []
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(_enrich_professor, prof, categories) for prof in professors
        ]
        for future in as_completed(futures):
            enriched.append(future.result())
    if categories:
        with_matches = [p for p in enriched if p.get("category_match_count", 0) > 0]
        if with_matches:
            enriched = with_matches
    enriched.sort(
        key=lambda prof: (prof.get("category_match_count", 0), prof.get("info_score", 0)),
        reverse=True,
    )
    return enriched


@app.route("/")
def home():
    return app.send_static_file("index.html")

DEFAULT_CATEGORIES = (
    "psychology, neuroscience, cognitive science, HCI, data science, wearable tech"
)


@app.route("/search", methods=["POST"])
def search():
    payload = request.get_json(silent=True) or {}
    school = (payload.get("school") or "").strip()
    category = (payload.get("category") or "").strip() or DEFAULT_CATEGORIES
    if not school:
        return jsonify({"error": "Please enter a university name."}), 400
    if not category:
        return jsonify({"error": "Please enter at least one research area."}), 400
    if not API_KEY:
        return jsonify({"error": "Missing HACKCLUB_API_KEY in .env"}), 500

    try:
        professors = _fetch_professors_from_ai(school, category)
    except requests.HTTPError as exc:
        print("SEARCH API ERROR:", exc)
        response = exc.response
        return jsonify({"error": _ai_error_message(exc, response)}), 502
    except requests.RequestException as exc:
        print("SEARCH API ERROR:", exc)
        response = getattr(exc, "response", None)
        return jsonify({"error": _ai_error_message(exc, response)}), 502
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        print("SEARCH PARSE ERROR:", exc)
        return jsonify({"error": AI_TOKEN_LIMIT_MSG}), 502

    filtered = []
    for prof in professors:
        cleaned = _sanitize_professor(prof)
        if cleaned:
            filtered.append(cleaned)

    if not filtered:
        return jsonify({
            "professors": [],
            "school": school,
            "category": category,
            "message": "No professors found for that school and research area. Try broader terms or fix the university name.",
        })

    categories = _parse_categories(category)
    ranked = _enrich_and_rank_professors(filtered, categories)
    warnings = _search_warnings(ranked)
    return jsonify({
        "professors": ranked,
        "school": school,
        "category": category,
        "warnings": warnings,
    })


@app.route("/api/check-url")
def check_url():
    url = normalize_url(request.args.get("url"))
    if not url:
        return jsonify({"ok": False})
    ok = is_reachable(url)
    return jsonify({"ok": ok, "url": url if ok else None})

# find professor using semantic scholar
@app.route("/professor")
def professor():
    name = request.args.get("name", "")
    school = request.args.get("school", "")

    try:
        topics_list = json.loads(request.args.get("topics", "[]"))
    except json.JSONDecodeError:
        topics_list = []

    scholar = _fetch_scholar_data(name)
    papers = scholar.get("papers", [])
    scholar_author_url = scholar.get("scholar_url")
    publications_warning = scholar.get("warning")
    if not papers and not publications_warning:
        publications_warning = (
            "No publications found on Semantic Scholar for this professor."
        )

    candidate_profile = request.args.get("profile_url") or request.args.get("profileUrl")
    faculty_profile_url = validated_faculty_url(candidate_profile)

    return render_template(
        "professor.html",
        name=name,
        school=school,
        role=request.args.get("role"),
        department=request.args.get("department"),
        summary=request.args.get("summary"),
        email=normalize_email(request.args.get("email")),
        faculty_profile_url=faculty_profile_url,
        scholar_author_url=scholar_author_url,
        research_topics=topics_list,
        papers=papers,
        publications_warning=publications_warning if not papers else None,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)