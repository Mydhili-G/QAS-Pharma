"""
Pharma Deal Intelligence Pipeline — Agentic version
-----------------------------------------------------
Claude (via OpenRouter) searches, reads, and extracts pharma deals.

Install:  pip install openai pydantic apscheduler python-dotenv
Run once: python main.py
Schedule: python main.py --schedule
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

load_dotenv()

client = OpenAI(
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

OUTPUT_FILE = "pharma_deals.json"


# ── MODELS ───────────────────────────────────────────────────────────────────

class Deal(BaseModel):
    company_a: Optional[str] = None
    company_b: Optional[str] = None
    deal_type: Optional[str] = None   # acquisition | merger | licensing | partnership | investment | other
    deal_value: Optional[str] = None  # e.g. "$2.3B" or "Undisclosed"
    therapeutic_area: Optional[str] = None
    deal_summary: str
    article_url: Optional[str] = None
    fetched_at: Optional[str] = None


class DealList(BaseModel):
    deals: list[Deal]


# ── AGENT ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a pharmaceutical industry analyst with web search access.

Your task:
1. Search for recent pharma deal news using these queries (one at a time):
   - pharma deal 2026
   - pharmaceutical acquisition 2026
   - biotech licensing deal 2026
   - drug partnership agreement 2026
   - pharma merger 2026

2. For each confirmed deal you find, extract structured data.

Rules:
- Only confirmed deals — no rumours, opinions, or background pieces
- Aim for 5–15 unique deals
- Read article content when the headline alone is insufficient
- After all searches are done, return your findings as valid JSON matching this schema exactly:

{
  "deals": [
    {
      "company_a": "string or null",
      "company_b": "string or null",
      "deal_type": "acquisition | merger | licensing | partnership | investment | other | null",
      "deal_value": "e.g. $2.3B or Undisclosed or null",
      "therapeutic_area": "e.g. oncology or null",
      "deal_summary": "1-2 sentence plain-English summary",
      "article_url": "source URL or null"
    }
  ]
}

Return ONLY the JSON. No markdown fences, no explanation."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web for current news and articles",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
        },
    }
]


def run_agent() -> list[Deal]:
    """Agentic loop: Claude searches and extracts until it returns final JSON."""
    import requests as req

    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "Find the latest pharma deals. Search all 5 queries then return the JSON."}]

    print("  Agent running...")

    while True:
        response = client.chat.completions.create(
            model="deepseek/deepseek-chat",
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            max_tokens=1600,
        )

        msg = response.choices[0].message
        messages.append(msg)

        # Done — parse the final JSON response
        if response.choices[0].finish_reason == "stop":
            return _parse_deals(msg.content or "")

        # Handle tool calls
        if msg.tool_calls:
            tool_results = []
            for tc in msg.tool_calls:
                query = json.loads(tc.function.arguments).get("query", "")
                print(f"    searching: {query[:70]}")

                try:
                    # Use DuckDuckGo HTML search (no API key needed)
                    search_resp = req.get(
                        "https://duckduckgo.com/html/",
                        params={"q": query},
                        headers={"User-Agent": "Mozilla/5.0"},
                        timeout=10,
                    )
                    # Extract snippets from results
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(search_resp.text, "html.parser")
                    results = []
                    for r in soup.select(".result")[:8]:
                        title = r.select_one(".result__title")
                        snippet = r.select_one(".result__snippet")
                        link = r.select_one("a.result__url")
                        if title and snippet:
                            results.append(
                                f"Title: {title.get_text(strip=True)}\n"
                                f"URL: {link.get_text(strip=True) if link else 'N/A'}\n"
                                f"Snippet: {snippet.get_text(strip=True)}"
                            )
                    content = "\n\n".join(results) or "No results found."
                except Exception as e:
                    content = f"Search failed: {e}"

                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": content,
                })

            messages.extend(tool_results)


def _parse_deals(text: str) -> list[Deal]:
    text = re.sub(r"```(?:json)?", "", text).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        print("  No JSON found in response")
        return []
    try:
        data = DealList.model_validate_json(match.group())
        now = datetime.now(timezone.utc).isoformat()
        for d in data.deals:
            d.fetched_at = now
        return data.deals
    except Exception as e:
        print(f"  Parse error: {e}")
        return []


# ── DIGEST ───────────────────────────────────────────────────────────────────

def deduplicate(deals: list[Deal]) -> list[Deal]:
    seen = set()
    unique = []
    for d in deals:
        key = (
            (d.company_a or "").lower(),
            (d.company_b or "").lower(),
            (d.deal_type or "").lower(),
        )
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


def print_digest(deals: list[Deal]):
    print("\n" + "=" * 70)
    print(f"  PHARMA DEAL DIGEST  —  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 70)
    for i, d in enumerate(deals, 1):
        print(f"\n{i}. {d.company_a or 'Unknown'}  x  {d.company_b or 'Unknown'}")
        print(f"   Type: {(d.deal_type or 'deal').title()}  |  Value: {d.deal_value or 'Undisclosed'}  |  Area: {d.therapeutic_area or 'N/A'}")
        print(f"   {d.deal_summary}")
        print(f"   -> {d.article_url or 'N/A'}")
    print("\n" + "=" * 70 + "\n")


def save_output(deals: list[Deal]):
    try:
        existing_dicts = []
        if os.path.exists(OUTPUT_FILE):
            with open(OUTPUT_FILE) as f:
                existing_dicts = json.load(f)

        existing = [Deal.model_validate(d) for d in existing_dicts]
        merged = deduplicate(existing + deals)

        with open(OUTPUT_FILE, "w") as f:
            json.dump([d.model_dump() for d in merged], f, indent=2)
        print(f"Saved {len(merged)} total deals to {OUTPUT_FILE}")
    except Exception as e:
        print(f"  save error: {e}")


# ── PIPELINE ─────────────────────────────────────────────────────────────────

def run_pipeline():
    print(f"\n{'='*60}")
    print(f"Pipeline run started: {datetime.now(timezone.utc).isoformat()}")
    print(f"{'='*60}")

    deals = run_agent()
    print(f"Deals found: {len(deals)}")

    deals = deduplicate(deals)
    print_digest(deals)
    save_output(deals)

    print("Pipeline complete.\n")


if __name__ == "__main__":
    import sys

    if "--schedule" in sys.argv:
        run_pipeline()
        scheduler = BlockingScheduler(timezone="UTC")
        scheduler.add_job(run_pipeline, "cron", hour=7, minute=0)
        print("Scheduler started — running daily at 07:00 UTC. Ctrl+C to stop.")
        try:
            scheduler.start()
        except KeyboardInterrupt:
            print("Scheduler stopped.")
    else:
        run_pipeline()
