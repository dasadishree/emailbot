from urllib.parse import urlparse
import re

import requests

_USER_AGENT = "ResearchEmailBot/1.0 (educational project)"

# prioritize safe/known sources
_TRUSTED_HOST_SUFFIXES = (
    "doi.org",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "semanticscholar.org",
    "ncbi.nlm.nih.gov",
)


# lots of checks to make sure url is working 
def normalize_url(url):
    # return working url
    if not url or not isinstance(url, str):
        return None
    url = url.strip()
    if not url or url.lower() in ("null", "none", "n/a", "#", "undefined"):
        return None
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.netloc.lower() in ("example.com", "localhost"):
        return None
    return url

def is_trusted_url(url):
    host = (urlparse(url).netloc or "").lower()
    return any(host == suffix or host.endswith("." + suffix) for suffix in _TRUSTED_HOST_SUFFIXES)

def is_reachable(url, timeout=5):
    url = normalize_url(url)
    if not url:
        return False
    headers = {"User-Agent": _USER_AGENT}
    try:
        response = requests.head(
            url, allow_redirects=True, timeout=timeout, headers=headers
        )
        if response.status_code in (405, 403, 404):
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=timeout,
                headers=headers,
                stream=True,
            )
            response.close()
        return response.status_code < 400
    except requests.RequestException:
        return False

def safe_link(url, timeout=5):
    url = normalize_url(url)
    if not url:
        return None
    if is_trusted_url(url):
        return url
    return url if is_reachable(url, timeout=timeout) else None

def validated_faculty_url(candidate):
    candidate = normalize_url(candidate)
    if not candidate:
        return None
    return candidate if is_reachable(candidate) else None

def resolve_profile_url(candidate, fallback=None):
    candidate = validated_faculty_url(candidate)
    if candidate:
        return candidate
    fallback = normalize_url(fallback)
    return fallback if fallback else None

# make sure link to paper is working
def paper_link(paper, verify_untrusted=True):
    external = paper.get("externalIds") or {}

    doi = external.get("DOI")
    if doi:
        return f"https://doi.org/{doi.strip()}"

    arxiv = external.get("ArXiv")
    if arxiv:
        return f"https://arxiv.org/abs/{arxiv}"

    pubmed = external.get("PubMed")
    if pubmed:
        return f"https://pubmed.ncbi.nlm.nih.gov/{pubmed}/"

    paper_id = paper.get("paperId")
    if paper_id:
        return f"https://www.semanticscholar.org/paper/{paper_id}"

    pdf = paper.get("openAccessPdf") or {}
    pdf_url = (pdf.get("url") or "").strip()
    if pdf_url.startswith(("http://", "https://")):
        if not verify_untrusted:
            return pdf_url
        return safe_link(pdf_url)

    return None


def normalize_email(email):
    # valid email
    if not email or not isinstance(email, str):
        return None
    email = email.strip()
    if not email or email.lower() in ("null", "none", "n/a", "unknown"):
        return None
    if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
        return None
    return email
