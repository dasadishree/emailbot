# server
from flask import Flask, request, jsonify, render_template
import requests
import json
import re
from dotenv import load_dotenv
import os

from url_utils import normalize_url, resolve_profile_url, paper_link, normalize_email, is_reachable

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

    return jsonify({"professors": filtered, "school": school})


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
    profile_url = normalize_url(candidate_profile) or scholar_author_url

    return render_template(
        "professor.html",
        name=name,
        school=school,
        role=request.args.get("role"),
        department=request.args.get("department"),
        summary=request.args.get("summary"),
        email=normalize_email(request.args.get("email")),
        profile_url=profile_url,
        scholar_author_url=scholar_author_url,
        research_topics=topics_list,
        papers=papers,
    )


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)