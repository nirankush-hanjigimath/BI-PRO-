"""
ai_analysis.py — Stage 4 (Gemini backend)
Sends structured market context to the Google Gemini API and returns
a concise, structured trading setup analysis.

Model: gemini-2.5-flash  (free-tier eligible, fast, consistent)
Auth:  GEMINI_API_KEY environment variable (no billing card required)
       Get one at: https://aistudio.google.com/apikey
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.5-flash:generateContent"
)

PROMPT_TEMPLATE = """You are an AI analyzing a multi-timeframe crypto futures setup.
Use ONLY the data below. Be concise. Do not claim certainty — this is rule-based pattern matching, not a guarantee.

Data:
Symbol: {symbol}
Confirmed Direction: {direction}

Timeframes Data:
{timeframes_data}

You MUST output ALL 8 lines below, in order, with no extra text before or after them. Do not stop before line 8. If a field is not applicable, write N/A.

SYMBOL: {symbol}
CONFIRMED DIRECTION: {direction}
TIMEFRAME AGREEMENT: <list each timeframe and its trend state, e.g. "15m: downtrend | 1h: downtrend">
ALIGNED CONDITIONS: <specific indicator conditions met, e.g. "price below EMA20/50, RSI oversold on 15m">
ENTRY ZONE: <entry price from shortest timeframe, or N/A>
STOP LOSS: <stop loss price, or N/A>
TARGET: <target price, or N/A>
NOTE: <one short sentence on the single biggest risk to this setup>
"""


def get_ai_analysis(data: dict, api_key: str | None = None) -> str:
    """
    Call the Gemini API and return the structured analysis text.

    Args:
        data: dict with keys:
              symbol, direction, timeframes_data (str)
        api_key: Gemini API key. Falls back to GEMINI_API_KEY env var.

    Returns:
        Analysis text string.

    Raises:
        RuntimeError on auth failure, network error, or unexpected response shape.
    """
    key = api_key or os.environ.get("GEMINI_API_KEY", "")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. "
            "Get a free key at https://aistudio.google.com/apikey "
            "and add it to your .env file."
        )

    symbol    = data.get("symbol", "?")
    direction = data.get("direction", "?")

    prompt = PROMPT_TEMPLATE.format(**data)

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "maxOutputTokens": 2000,
            "temperature": 0.1,
        },
    }

    logger.info(
        f"[{symbol}/MTF] Calling Gemini API (direction: {direction}) …"
    )

    try:
        resp = requests.post(
            f"{GEMINI_URL}?key={key}",
            json=payload,
            timeout=15,
        )
    except requests.ConnectionError as exc:
        raise RuntimeError(f"Gemini API connection error: {exc}") from exc
    except requests.Timeout:
        raise RuntimeError("Gemini API request timed out after 15 s.")

    if resp.status_code == 400:
        raise RuntimeError(
            f"Gemini API returned 400 Bad Request: {resp.text[:300]}"
        )
    if resp.status_code == 429:
        raise RuntimeError(
            "Gemini API rate-limited (429). "
            "The cooldown window should prevent this in normal operation."
        )
    if resp.status_code == 403:
        raise RuntimeError(
            "Gemini API returned 403 Forbidden — check your GEMINI_API_KEY."
        )

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(f"Gemini API HTTP error: {exc}") from exc

    result = resp.json()

    try:
        text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        logger.error(f"Unexpected Gemini response structure: {result}")
        raise RuntimeError(
            f"Could not parse Gemini response: {exc}. "
            f"Raw response (truncated): {str(result)[:400]}"
        ) from exc

    logger.info(
        f"[{symbol}/MTF] Gemini responded ({len(text)} chars)."
    )
    return text.strip()
