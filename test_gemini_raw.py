import os, requests, json
from dotenv import load_dotenv

load_dotenv()

key = os.environ.get('GEMINI_API_KEY')
prompt = """You are an AI analyzing a crypto futures setup.
Use ONLY the data below. Be concise (under 130 words). Do not claim certainty — this is rule-based pattern matching, not a guarantee.

Data:
Symbol: XLMUSDT
Timeframe: 15m
Current price: 0.21
Triggered condition(s): BAND_REJECTION_UP, RSI_OVERSOLD

Indicators:
- Bollinger Bands: upper=0.22, mid=0.215, lower=0.21
- RSI(14): 25.0
- EMA20: 0.215, EMA50: 0.22
- Recent swing high: 0.23, swing low: 0.20
- Last 10 closes: 0.21, 0.21, 0.21

Return your analysis using EXACTLY the following 7 lines. Do not add any conversational text. If a field is not applicable, output "N/A".

TREND: <uptrend/downtrend/ranging>
SETUP TYPE: <continuation/reversal/unclear>
ENTRY ZONE: <price range or N/A>
STOP LOSS: <price or N/A>
TARGET: <price or N/A>
CONFIDENCE: <LOW/MEDIUM/HIGH>
NOTE: <one short sentence flagging the single biggest risk to this setup>"""

payload = {
    'contents': [{'parts': [{'text': prompt}]}],
    'generationConfig': {
        'maxOutputTokens': 250,
        'temperature': 0.3,
    },
}
url = f'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}'
resp = requests.post(url, json=payload).json()
print(json.dumps(resp, indent=2))
