import json
import os
import re
from pathlib import Path
from typing import List

from google import genai
from google.genai import types
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# load the product catalog we scraped earlier
CATALOG_PATH = Path(__file__).parent.parent / "data" / "catalog.json"

def load_catalog() -> list[dict]:
    if not CATALOG_PATH.exists():
        raise RuntimeError(f"Catalog file missing at {CATALOG_PATH}. Run scrape_catalog.py first.")
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)

products = load_catalog()

def format_catalog_for_prompt() -> str:
    lines = []
    for item in products:
        test_types = ", ".join(item.get("test_types", [])) or "N/A"
        desc = item.get("description", "")
        remote = "Yes" if item.get("remote_testing") else "No"
        adaptive = "Yes" if item.get("adaptive_irt") else "No"
        lines.append(
            f"- Name: {item['name']}\n"
            f"  URL: {item['url']}\n"
            f"  Test Types: {test_types}\n"
            f"  Remote Testing: {remote}\n"
            f"  Adaptive/IRT: {adaptive}\n"
            f"  Description: {desc}\n"
        )
    return "\n".join(lines)

catalog_text = format_catalog_for_prompt()


class Message(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: List[Message]

class Recommendation(BaseModel):
    name: str
    url: str
    test_type: str

class ChatResponse(BaseModel):
    reply: str
    recommendations: List[Recommendation]
    end_of_conversation: bool


# this is the main instruction we give to the AI
SYSTEM_PROMPT = f"""You are an SHL Assessment Recommender agent. Your ONLY job is to help hiring managers and recruiters find the right SHL assessments from the SHL Individual Test Solutions catalog.

CATALOG (your ONLY source of truth):
{catalog_text}

STRICT RULES:
1. ONLY recommend assessments that appear in the catalog above. NEVER invent or hallucinate assessments.
2. ONLY return URLs that appear verbatim in the catalog above.
3. You ONLY discuss SHL assessments. Refuse all off-topic requests.
4. Do NOT recommend on the very first message if the query is vague. Ask at least one clarifying question first.
5. Once you have enough context, recommend 1-10 assessments.
6. When the user refines their request, UPDATE the shortlist.
7. Honor the 8-turn cap: if by turn 7 you still lack context, make your best recommendation anyway.

RESPONSE FORMAT - always respond with valid JSON:
{{
  "reply": "<your conversational response>",
  "recommendations": [
    {{"name": "<exact name from catalog>", "url": "<exact url from catalog>", "test_type": "<letter code>"}}
  ],
  "end_of_conversation": <true or false>
}}

- recommendations is [] when still gathering context.
- end_of_conversation is true ONLY when need is fully addressed and shortlist was provided.
- Do NOT include any text outside the JSON object.

TEST TYPE CODES: A=Ability & Aptitude, B=Biodata & SJT, C=Competencies, D=Development & 360,
E=Assessment Exercises, K=Knowledge & Skills, M=Motivation, P=Personality & Behavior, S=Simulations"""


gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
GEMINI_MODEL = "gemini-2.5-flash"


def extract_json(raw: str) -> dict:
    # sometimes the model wraps response in markdown code blocks, strip that
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # fallback: try to find a JSON object anywhere in the text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise


def filter_valid_products(raw_list: list) -> list[Recommendation]:
    # make sure we only return products that actually exist in our catalog
    result = []
    valid_urls = {p["url"] for p in products}
    name_lookup = {p["name"].lower(): p for p in products}

    for item in raw_list:
        name = item.get("name", "")
        url = item.get("url", "")
        test_type = item.get("test_type", "")

        if url not in valid_urls:
            # try matching by name if URL is wrong
            match = name_lookup.get(name.lower())
            if match:
                url = match["url"]
            else:
                continue  # skip anything not in catalog

        result.append(Recommendation(name=name, url=url, test_type=test_type))

    return result[:10]


def get_recommendation(messages: List[Message]) -> ChatResponse:
    # build conversation history in the format Gemini expects
    history = []
    for m in messages[:-1]:
        role = "model" if m.role == "assistant" else "user"
        history.append(types.Content(role=role, parts=[types.Part(text=m.content)]))

    latest_message = messages[-1].content

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=history + [types.Content(role="user", parts=[types.Part(text=latest_message)])],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.2,
            ),
        )
        raw_text = response.text

    except Exception as e:
        print("Gemini API error:", str(e))
        return ChatResponse(
            reply=f"Something went wrong: {str(e)}",
            recommendations=[],
            end_of_conversation=False
        )

    try:
        parsed = extract_json(raw_text)
    except Exception:
        return ChatResponse(
            reply="Sorry, I had trouble understanding that. Could you rephrase?",
            recommendations=[],
            end_of_conversation=False
        )

    reply = parsed.get("reply", "")
    raw_recs = parsed.get("recommendations", [])
    done = bool(parsed.get("end_of_conversation", False))

    recommendations = filter_valid_products(raw_recs)

    # don't mark conversation as done if we haven't given any recommendations
    if done and not recommendations:
        done = False

    return ChatResponse(reply=reply, recommendations=recommendations, end_of_conversation=done)


app = FastAPI(
    title="SHL Assessment Recommender",
    description="Conversational agent for SHL Individual Test Solutions",
    version="1.0.0",
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    if not request.messages:
        raise HTTPException(status_code=400, detail="messages cannot be empty")

    # count how many times the user has spoken
    user_turns = sum(1 for m in request.messages if m.role == "user")
    if user_turns > 8:
        return ChatResponse(
            reply="We've reached the end of our conversation. Here are my final recommendations.",
            recommendations=[],
            end_of_conversation=True,
        )

    try:
        return get_recommendation(request.messages)
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))