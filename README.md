# Pharma Deal Pipeline

Automatically tracks pharmaceutical acquisitions, mergers, licensing deals, and partnerships. Runs daily via GitHub Actions and saves results to `output.json`.

## How it works

An AI agent (DeepSeek via OpenRouter) searches the web for recent pharma deal news, reads the articles, and extracts structured deal data — no scraping or RSS parsing.

## Setup

### 1. Clone the repo
```bash
git clone https://github.com/your-username/pharma-deal-pipeline
cd pharma-deal-pipeline
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Add your API key
Create a `.env` file:
```
OPENROUTER_API_KEY=your_key_here
```
Get a free key at [openrouter.ai](https://openrouter.ai).

### 4. Run manually
```bash
python main.py
```

## Automation (GitHub Actions)

The pipeline runs automatically every day at 9am IST. To enable it on your fork:

1. Go to your repo → **Settings → Secrets and variables → Actions**
2. Click **New repository secret**
3. Name: `OPENROUTER_API_KEY`, Value: your key
4. The workflow in `.github/workflows/daily.yml` handles the rest — it runs the pipeline and commits the updated `output.json` back to the repo automatically

You can also trigger a manual run from the **Actions** tab → **Daily Pharma Deal Pipeline** → **Run workflow**.

## Output

Results are saved to `output.json` — an array of deal objects:

```json
[
  {
    "company_a": "Novo Nordisk",
    "company_b": "Akero Therapeutics",
    "deal_type": "acquisition",
    "deal_value": "$4.7B",
    "therapeutic_area": "MASH",
    "deal_summary": "Novo Nordisk acquires Akero Therapeutics to deepen its MASH pipeline.",
    "article_url": "https://...",
    "fetched_at": "2026-03-06T04:08:00+00:00"
  }
]
```
