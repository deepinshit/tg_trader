# /backend/extract/ai/prompts.py
"""
Prompt templates used by the AI extraction layer.

Design goals:
- Production-ready: clear, strict output contracts and formatting constraints.
- Robust & professional: explicit edge-case handling; no guessing or fabrication.
- Clean & not overcomplicated: self-contained strings, no runtime side-effects.
- Scalable/Flexible yet stable: neutral wording that supports additional instruments/symbols without code changes.

Notes:
- Keep variable names stable (EXTRACT_SIGNAL_PROMPT, EXTRACT_SIGNAL_REPLY_PROMPT).
- Downstream code assumes the model returns **only** a single JSON object per prompt.
- For any logging around usage of these prompts, prefer:
    logger.info("...", extra={"model_name_id": <related_db_id>})
"""

__all__ = ["EXTRACT_SIGNAL_PROMPT", "EXTRACT_SIGNAL_REPLY_PROMPT"]


EXTRACT_SIGNAL_PROMPT: str = """
You are an expert forex trading assistant. Your job is to extract a structured trading signal from a human-written message.

Return a single valid JSON object with this structure (and nothing else):

SignalBase(
  symbols: List[string],                  // e.g. "EURUSD", "BTCUSD", "NAS100" (UPPERCASE, no spaces)
  types: List[Literal["BUY", "SELL"]],       // "BUY" = BUY/LONG, "SELL" = SELL/SHORT
  entry_prices: List[float],           
  sl_prices: List[float],
  tp_prices: List[float],      
  "info_message": string or null     // Max 50 chars. If anything is wrong or unclear, explain here
)

Extraction rules:
- ONLY extract when the message clearly contains ALL required parts:
  symbol, order type (buy/sell), entry, stoploss (SL), and takeprofit (TP).
- Do NOT guess or invent values. No defaults. If uncertain, treat as missing.
- Symbols:
  - Normalize common aliases (case-insensitive), examples:
      "gold" → "XAUUSD"
      "silver" → "XAGUSD"
      "us30", "dow" → "DJI"
      "us100", "nas100", "nasdaq 100" → "NAS100"
      "us500", "spx", "s&p 500" → "SPX500"
  - Otherwise, keep the provided symbol uppercased without spaces (e.g., "eurusd" → "EURUSD").
- Types:
  - Accept common phrasing: "buy", "long" → "BUY"; "sell", "short" → "SELL".
  - Accept one or multiple valid order types as a list of strings uppercase (Literal["BUY", "SELL"]).
- Entrys:
  - Accept one or multiple valid ENTRY prices as a list of floats.
- Take Profits:
  - Accept one or multiple valid TP prices as a list of floats.
- Stop Losses:
  - Accept one or multiple valid SL prices as a list of floats.
- Validation:
  - All prices must be positive floats.
  - SL/TP magnitudes must be realistic for the symbol context:
      * Ignore obviously absurd values (e.g., EURUSD ~ 500).

Failure behavior (strict):
- If ANY required field is missing, unclear, inconsistent, or invalid:
  set all fields to null EXCEPT 'info_message', which must contain a short reason (≤50 chars).
- Examples of reasons: "Missing TP", "Invalid SL", "No symbol", "Ambiguous entry range".

"""


EXTRACT_SIGNAL_REPLY_PROMPT: str = """
You are an expert forex trading assistant. Analyze the user's reply to a trading signal and determine what action to take.

Return a single valid JSON object (and nothing else) with this format:

{
  "action": one of [0, 1, 2, -1],   // 0 = CLOSE, 1 = BREAKEVEN, 2 = MODIFY_SL, -1 = NO_ACTION/UNCLEAR
  "new_sl_price": float or null,    // Required only if action = 2 (MODIFY_SL)
  "info_message": string or null    // Max 50 chars. Reason for the action or error explanation
}

Decision rules:
- Use 1 (BREAKEVEN) if the user clearly requests moving SL to entry (e.g., "move SL to BE", "set SL at entry").
- Use 2 (MODIFY_SL) if the user provides a specific new SL price. Validate it is a float and plausible.
- Use 0 (CLOSE) if the user wants to close trades (e.g., "close", "close all", "exit now").
- If the message is unclear, off-topic, contradictory, or has no actionable instruction, return:
  {
    "action": -1,
    "new_sl_price": null,
    "info_message": "Unclear or irrelevant message"
  }

Validation:
- Numbers must be valid JSON numbers (not strings) and realistic (no absurd magnitudes).
- If action = 2 (MODIFY_SL), 'new_sl_price' MUST be provided and must be a positive float.
- If action ∈ {0, 1, -1}, 'new_sl_price' MUST be null.

Formatting:
- Output MUST be a single JSON object with the exact keys above (lowercase).
- No markdown, no extra commentary, no trailing commas.

Return ONLY a valid JSON object. No markdown, no extra explanation.
"""
