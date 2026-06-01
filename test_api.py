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
            "content": "You are a research assistant. A