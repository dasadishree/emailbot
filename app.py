# server
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Flask, request, jsonify, render_template
import requests
import json
import re
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
app = Flask(__name__)


def _parse_llm_json(raw_text):
    text = (raw_text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return json.loads(text)


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


def _sanitize_professor(prof):
    if not isinstance(prof, dict):
        return None
    role = (prof.get("role") or "").lower()
    if "emeritus" in role:
        return None
    topics = prof.get("topics")
    if not isinstance(topics, list):
        topics = []
    return {
        **prof,
        "role": prof.get("role") or "",
        "department": prof.get("department") or "",
        "topics": topics,
        "research_summary": prof.get("research_summary") or "",
        "email": normalize_email(prof.get("email")),
        "profile_url": normalize_url(prof.get("profile_url")),
    }


def _fetch_scholar_meta(name):
    try:
        response = requests.get(
            "https://api.semanticscholar.org/graph/v1/author/search",
            params={
                "query": name,
                "limit": 10,
                "fields": "name,paperCount,authorId,papers.year",
            },
            timeout=10,
        )
        if response.status_code != 200:
            return {}
        results = response.json().get("data", [])
        author = _pick_best_author(results, name)
        if not author:
            return {}
        papers = author.get("papers") or []
        years = [p.get("year") for p in papers if p.get("year")]
        author_id = author.get("authorId")
        return {
            "paper_count": author.get("paperCount") or len(papers),
            "latest_year": max(years) if years else None,
            "scholar_url": (
                f"https://www.semanticscholar.org/author/{author_id}"
                if author_id
                else None
            ),
        }
    except requests.RequestException:
        return {}


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


def _enrich_professor(prof):
    profile_candidate = prof.get("profile_url")
    prof["profile_url"] = validated_faculty_url(profile_candidate)
    scholar = _fetch_scholar_meta(prof.get("name", ""))
    prof["scholar_url"] = scholar.get("scholar_url")
    prof["publication_count"] = scholar.get("paper_count", 0)
    prof["latest_publication_year"] = scholar.get("latest_year")
    prof["info_score"] = _compute_info_score(prof, scholar)
    return prof


def _enrich_and_rank_professors(professors):
    if not professors:
        return []
    enriched = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(_enrich_professor, prof) for prof in professors]
        for future in as_completed(futures):
            enriched.append(future.result())
    enriched.sort(key=lambda prof: prof.get("info_score", 0), reverse=True)
    return enriched


@app.route("/")
def home():
    return app.send_static_file("index.html")

@app.route("/search", methods=["POST"])
def search():
    payload = request.get_json(silent=True) or {}
    school = (payload.get("school") or "").strip()
    if not school:
        return jsonify({"error": "Please enter a university name."}), 400
    if not API_KEY:
        return jsonify({"error": "Missing HACKCLUB_API_KEY in .env"}), 500

    try:
        response = requests.post(
            "https://ai.hackclub.com/proxy/v1/chat/completions",
            headers={
                "Authorization": "Bearer " + API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "model": "qwen/qwen3-32b",
                "messages": [
                    {
                        "role": "system",
                        "content": "You are a research assistant. Always respond with raw JSON only - no explanation, no markdown, no backticks. Just the JSON object.",
                    },
                    {
                        "role": "user",
                        "content": f"""List professors at {school} who work in psychology , neuroscience, cognitive science, HCI, data science, or wearable tech.

                    Rules
                    - Do NOT include emeritus professors
                    - Only include professors who have published research or had an active lab in the last 10 years
                    - Do NOT include anyone who is publicly known to not accept high school students or interns
                    - If you are unsure whether someone accepts high schoolers, include them

                    Return a JSON object with a 'professors' key containing a list. Each professor should have: name, role, department, topics (list), research_summary, email (or null if unknown), profile_url (full https URL to their official university faculty page only — use null if you are not certain the exact page exists).""",
                    },
                ],
            },
            timeout=120,
        )
        response.raise_for_status()
        api_data = response.json()
        raw_text = api_data["choices"][0]["message"]["content"]
        print("RAW RESPONSE:", raw_text)
        parsed = _parse_llm_json(raw_text)
        professors = _extract_professors(parsed)
    except requests.RequestException as exc:
        print("SEARCH API ERROR:", exc)
        return jsonify({"error": "Could not reach the AI service. Try again in a moment."}), 502
    except (KeyError, IndexError, json.JSONDecodeError, TypeError) as exc:
        print("SEARCH PARSE ERROR:", exc)
        return jsonify({"error": "Could not read professor results. Try searching again."}), 502

    filtered = []
    for prof in professors:
        cleaned = _sanitize_professor(prof)
        if cleaned:
            filtered.append(cleaned)

    ranked = _enrich_and_rank_professors(filtered)
    return jsonify({"professors": ranked, "school": school})


@app.route("/api/check-url")
def check_url():
    url = normalize_url(request.args.get("url"))
    if not url:
        return jsonify({"ok": False})
    ok = is_reachable(url)
    return jsonify({"ok": ok, "url": url if ok else None})

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


# find professor using semantic scholar
@app.route("/professor")
def professor():
    name = request.args.get("name", "")
    school = request.args.get("school", "")

    try:
        topics_list = json.loads(request.args.get("topics", "[]"))
    except json.JSONDecodeError:
        topics_list = []

    papers = []
    scholar_author_url = None
    search_response = requests.get(
        "https://api.semanticscholar.org/graph/v1/author/search",
        params={
            "query": name,
            "limit": 10,
            "fields": "name,paperCount,authorId,papers.paperId,papers.title,papers.year,papers.externalIds,papers.openAccessPdf",
        },
        timeout=15,
    )
    if search_response.status_code == 200:
        results = search_response.json().get("data", [])
        author = _pick_best_author(results, name)
        if author:
            author_id = author.get("authorId")
            if author_id:
                scholar_author_url = f"https://www.semanticscholar.org/author/{author_id}"
            raw_papers = author.get("papers") or []
            raw_papers.sort(key=lambda p: p.get("year") or 0, reverse=True)
            for p in raw_papers[:15]:
                link = paper_link(p)
                papers.append({
                    "title": p.get("title"),
                    "year": p.get("year"),
                    "link": link,
                })

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
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)