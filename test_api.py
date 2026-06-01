import requests
import json
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("HACKCLUB_API_KEY")

url = "https://ai.hackclub.com/proxy/v1/chat/completions"

headers = {
    "Authorization": "Bearer " + API_KEY,
    "Content-Type": "application/json"
}

school = "MIT"

# prompt to return list of professors in stuff im interested in
body = {
    "model": "qwen/qwen3-32b",
    "messages": [
        {
            "role": "system", 
            "content": "You are a research assistant. Always respond with raw JSON only - no explanation, no markdown, no backticks. Just the JSON object."
        },
        {
            "role": "user",
            "content": f"""List professors at {school} who work in psychology, neuroscience, cognitive science, HCI, data science, or wearable tech.
            
            Rules: 
            - DO NOT include emeritus professors
            - Only include professors who have published research or had an active lab in the last 10 years
            - Do NOT include anyone who is publicly known to not accept high school students or interns
            - If you are unsure whether someone accepts high schoolers, include them

            Return a JSON object with a 'professors' key containing a list. Each professor should have: name, role, department, topics (list), research_summary. """
        }
    ]
}

response = requests.post(url, headers=headers, json=body)
data = response.json()

# parse json and filter out emeritus and also fix prof & other details to clean up the data a bit
raw_text = data["choices"][0]["message"]["content"]
parsed = json.loads(raw_text)
professors = None
for key in parsed:
    if "prof" in key.lower():
        professors = parsed[key]
        break

filtered = []
for prof in professors:
    role = prof.get("role", "").lower()
    if "emeritus" not in role:
        filtered.append(prof)

print(f"Found {len(filtered)} professors at {school}:\n")
for prof in filtered:
    print(f" {prof['name']} - {prof['role']}, {prof['department']}")
    print(f" Topics: {', '.join(prof['topics'])}")
    print(f" {prof['research_summary']}")
    print()