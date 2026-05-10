# SHL Assessment Recommender

A conversational AI agent that recommends SHL Individual Test Solutions based on natural language hiring needs.

## Architecture

```
User → POST /chat (full history) → FastAPI → Claude (claude-sonnet-4) → JSON response
                                         ↑
                              catalog.json (scraped SHL catalog)
```

## Setup (do this in order)

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set your Anthropic API key
```bash
export ANTHROPIC_API_KEY=sk-ant-...
```
Get a free key at https://console.anthropic.com — the free tier is enough for this assignment.

### 3. Scrape the SHL catalog (run ONCE)
```bash
python scrape_catalog.py
```
This creates `data/catalog.json` with all Individual Test Solutions.
Takes ~2–5 minutes. Requires internet access to shl.com.

**If scraping fails** (403/bot protection), manually copy the catalog:
- Visit https://www.shl.com/solutions/products/product-catalog/
- Filter to "Individual Test Solutions"  
- Copy product names + URLs into `data/catalog.json` using this format:
```json
[
  {
    "name": "Verify Numerical Reasoning",
    "url": "https://www.shl.com/solutions/products/product-catalog/view/verify-numerical-reasoning/",
    "test_types": ["A"],
    "remote_testing": true,
    "adaptive_irt": false,
    "description": "Measures ability to work with numerical data..."
  }
]
```

### 4. Run locally
```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Test locally
```bash
python test_local.py
```

### 6. Deploy to Render (free)
1. Push this folder to a GitHub repo
2. Go to https://render.com → New → Web Service → Connect your repo
3. Build command: `pip install -r requirements.txt`
4. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Add environment variable: `ANTHROPIC_API_KEY` = your key
6. Deploy → copy the public URL

## API

### GET /health
```json
{"status": "ok"}
```

### POST /chat
Request:
```json
{
  "messages": [
    {"role": "user", "content": "I need to hire a Java developer"},
    {"role": "assistant", "content": "What seniority level?"},
    {"role": "user", "content": "Mid-level, 4 years experience"}
  ]
}
```

Response:
```json
{
  "reply": "Here are 4 assessments suited for a mid-level Java developer...",
  "recommendations": [
    {"name": "Java 8 (New)", "url": "https://www.shl.com/...", "test_type": "K"}
  ],
  "end_of_conversation": false
}
```

## Design choices

- **LLM**: Claude Sonnet 4 via Anthropic API (free tier available)
- **Retrieval**: Full catalog injected into system prompt (catalog is small enough ~50-100 items)
- **Stateless**: No DB, no session — full history passed each call per spec
- **Schema enforcement**: JSON parsed and validated; hallucinated URLs stripped
- **Guardrails**: System prompt + post-processing validation against catalog URLs
