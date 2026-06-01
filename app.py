# server
from flask import Flask, request, jsonify
import requests
import json
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("HACKCLUB_API_KEY")
app=Flask(__name__)

@app.route("/")
def home():
    return app.send_static_file("index.html")

@app.route("/search", methods=["POST"])
def search():
    school = request.json["school"]

    response = requests.post(
        "https://ai.hackclub.com/proxy/v1/chat/completions",
        headers={
            "Authorization": "Bearer " + API_KEY,
            "Content-Type": "application/json"
        },
        json={
            "model": "qwen/qwen3-32b",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a research assistant. Always respond with raw JSON only - no explanation, no markdown, no backticks. Just the JSON object."
                },
                {
                    "role": "user",
                    "content": f"""List professors at {school} who work in psychology , neuroscience, cognitive science, HCI, data science, or wearable tech.

                    Rules
                    - Do NOT include emeritus professors
                    - Only include professors who have published research or had an active lab in the last 10 years
                    - Do NOT include anyone who is publicly known to not accept high school students or interns
                    - If you are unsure whether someone accepts high schoolers, include them

                    Return a JSON object with a 'professors' key containing a list. Each professor should have: name, role, department, topics (list), research_summary."""
                }
            ]
        }
    )
    raw_text = response.json()["choices"][0]["message"]["content"]
    parsed = json.loads(raw_text)
    professors = []
    for key in parsed:
        if "prof" in key.lower():
            professors = parsed[key]
            break
    filtered = []
    for prof in professors: 
        role = prof.get("role", "").lower()
        if "emeritus" not in role:
            filtered.append(prof)

    return jsonify({"professors": filtered, "school": school})

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)