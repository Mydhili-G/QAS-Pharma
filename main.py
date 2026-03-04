import feedparser
import urllib.parse
import requests
import json
import os
import time
import re
from dotenv import load_dotenv
from newspaper import Article
from bs4 import BeautifulSoup
import trafilatura

# ---------------- ENV ----------------
load_dotenv()
API_KEY = os.getenv("OPENROUTER_API_KEY")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------- FETCH ----------------
def fetch_articles():
    query = urllib.parse.quote(
        "pharma deal OR pharmaceutical acquisition OR biotech partnership OR drug licensing"
    )

    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    feed = feedparser.parse(url)

    articles = []

    for entry in feed.entries:
        # Try to get publisher domain from entry.source
        source_url = None
        if hasattr(entry, 'source') and isinstance(entry.source, dict):
            source_url = entry.source.get('href') or entry.source.get('url')

        # Use BeautifulSoup to parse summary for any non-Google links
        real_link = None
        if hasattr(entry, 'summary'):
            soup = BeautifulSoup(entry.summary, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                href = a_tag['href']
                if href.startswith('http') and 'google.com' not in href:
                    real_link = href
                    break

        articles.append({
            "title": entry.title,
            "link": real_link or entry.link,
            "source_url": source_url,
            "summary": entry.get('summary', '')
        })

    return articles


# ---------------- DEDUP ----------------
def deduplicate(articles):
    seen = set()
    unique = []
    for a in articles:
        if a["link"] not in seen:
            seen.add(a["link"])
            unique.append(a)
    return unique


# ---------------- FILTER ----------------
def filter_articles(articles):
    keywords = ["deal", "acqui", "merge", "partner", "licens"]
    filtered = []
    for a in articles:
        text = (a["title"] + a["summary"]).lower()
        if any(k in text for k in keywords):
            filtered.append(a)
    return filtered


# ---------------- URL RESOLVE ----------------
def resolve_url(article):
    """
    Get the real article URL using multiple strategies:
    1. Link is already non-Google - use it directly
    2. Search publisher site via DuckDuckGo using source domain + title
    3. Search DuckDuckGo using just the title
    """
    url = article["link"]
    title = article["title"]
    source_url = article.get("source_url")

    # Strategy 1: already a real URL
    if 'google.com' not in url:
        try:
            response = requests.get(url, headers=HEADERS, allow_redirects=True, timeout=10)
            return response.url
        except Exception as e:
            print(f"  resolve direct failed: {e}")

    # Strategy 2: search publisher site using title
    if source_url:
        try:
            domain = re.sub(r'https?://(www\.)?', '', source_url).strip('/')
            search_query = urllib.parse.quote(f'site:{domain} {title[:80]}')
            search_url = f"https://duckduckgo.com/html/?q={search_query}"
            response = requests.get(search_url, headers=HEADERS, timeout=10)
            soup = BeautifulSoup(response.text, 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                if domain in href and 'google.com' not in href and 'duckduckgo.com' not in href:
                    return href
        except Exception as e:
            print(f"  resolve site search failed: {e}")

    # Strategy 3: DuckDuckGo search by title only
    try:
        search_query = urllib.parse.quote(title[:100])
        search_url = f"https://duckduckgo.com/html/?q={search_query}"
        response = requests.get(search_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        for a in soup.find_all('a', class_='result__a', href=True):
            href = a['href']
            if 'google.com' not in href and 'duckduckgo.com' not in href:
                return href
    except Exception as e:
        print(f"  resolve DDG search failed: {e}")

    return None


# ---------------- SCRAPE ----------------
def fetch_html(url):
    try:
        response = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
        response.raise_for_status()
        return response.text, response.url
    except Exception as e:
        print(f"  fetch_html failed: {e}")
        return None, url


def get_article_text(url):
    html, final_url = fetch_html(url)
    if not html:
        return None, url

    # Try trafilatura first
    try:
        text = trafilatura.extract(html)
        if text and len(text.strip()) >= 200:
            return text, final_url
    except Exception as e:
        print(f"  trafilatura error: {e}")

    # Fallback 1: newspaper3k with pre-fetched HTML
    try:
        article = Article(url)
        article.set_html(html)
        article.parse()
        if article.text and len(article.text.strip()) >= 200:
            return article.text, final_url
    except Exception as e:
        print(f"  newspaper error: {e}")

    # Fallback 2: BeautifulSoup paragraph extraction
    try:
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            tag.decompose()
        text = ' '.join(p.get_text(strip=True) for p in soup.find_all('p'))
        if text and len(text.strip()) >= 200:
            return text, final_url
    except Exception as e:
        print(f"  BeautifulSoup error: {e}")

    return None, final_url


def enrich_with_text(articles, sleep_seconds=1):
    enriched = []
    for a in articles:
        real_url = resolve_url(a)

        if not real_url:
            print(f"  Skipped (no URL): {a['title'][:60]}")
            time.sleep(sleep_seconds)
            continue

        print(f"Scraping: {real_url[:90]}")
        text, final_url = get_article_text(real_url)

        if text:
            enriched.append({**a, "text": text, "link": final_url})
        else:
            print(f"  Skipped (no content): {real_url[:80]}")

        time.sleep(sleep_seconds)

    return enriched


# ---------------- LLM ----------------
PROMPT = """
Extract structured data from this pharma news article.

Return ONLY valid JSON with:
{
  "company_a": "",
  "company_b": "",
  "deal_type": "",
  "deal_value": "",
  "deal_summary": "",
  "is_deal": true
}

Rules:
- Use null or "Undisclosed" if unknown
- is_deal must be true ONLY if an actual deal is confirmed

Article:
"""


def call_llm(text, retries=2):
    for attempt in range(retries + 1):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {API_KEY}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": "deepseek/deepseek-chat",
                    "messages": [
                        {"role": "user", "content": PROMPT + text[:4000]}
                    ]
                },
                timeout=30
            )

            if response.status_code != 200:
                print(f"  LLM HTTP {response.status_code}: {response.text[:200]}")
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                return None

            return response.json()

        except Exception as e:
            print(f"  LLM error (attempt {attempt + 1}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    return None


# ---------------- PARSE ----------------
def parse_llm_output(response):
    try:
        content = response["choices"][0]["message"]["content"]
        content = content.replace("```json", "").replace("```", "").strip()
        return json.loads(content)
    except Exception as e:
        print(f"  parse error: {e}")
        return None


def is_valid_deal(data):
    val = data.get("is_deal")
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("true", "yes", "1")
    if isinstance(val, int):
        return val == 1
    return False


# ---------------- PROCESS ----------------
def extract_with_llm(article):
    response = call_llm(article["text"])
    if not response:
        return None
    parsed = parse_llm_output(response)
    if parsed:
        parsed["article_url"] = article["link"]
        return parsed
    return None


def process_articles(articles):
    results = []
    for a in articles:
        print(f"Processing: {a['title'][:80]}")
        data = extract_with_llm(a)
        if data and isinstance(data, dict) and is_valid_deal(data):
            results.append(data)
    return results


# ---------------- SAVE ----------------
def save_output(results, path="output.json"):
    try:
        with open(path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"Saved {len(results)} results to {path}")
    except Exception as e:
        print(f"  save error: {e}")


# ---------------- PIPELINE ----------------
def run_pipeline(max_results=None):
    print("Starting pipeline...")

    articles = fetch_articles()
    print(f"Fetched: {len(articles)}")

    articles = deduplicate(articles)
    print(f"After dedup: {len(articles)}")

    articles = filter_articles(articles)
    print(f"After filter: {len(articles)}")

    articles = enrich_with_text(articles)
    print(f"After scraping: {len(articles)}")

    results = process_articles(articles)
    print(f"Final results: {len(results)}")

    if max_results is not None:
        print(f"Truncating to {max_results} results")
        results = results[:max_results]

    save_output(results)
    print("Pipeline complete.")


# ---------------- ENTRY ----------------
if __name__ == "__main__":
    run_pipeline()
