# QAS-Pharma
Python script that runs automatically once per day and produces a digest of 5–10 confirmed pharmaceutical deals

01
Scrape: Query Google News RSS (or equivalent) using keywords: 'pharma deal', 'pharmaceutical
acquisition', 'biotech licensing', 'drug partnership', 'pharma merger'. Collect 15–20 candidate articles
per run.
02 Filter: Identify which articles are actually about a deal (not opinion, background, or unrelated news)
using a headline/snippet keyword check or a lightweight LLM classifier call.
03 Extract: Fetch full article body text from the source URL. Clean boilerplate using newspaper3k or
trafilatura.
04 Parse via LLM: Send cleaned text to an LLM API (OpenRouter or DeepSeek — see Context). Extract
structured JSON with the fields defined below.
05 Digest: De-duplicate results and display (or save) a clean human-readable digest of the top 5–10
deals.
06 Schedule: Run the full pipeline once per day via the schedule library, APScheduler, cron, or GitHub
Actions.
