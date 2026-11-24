"""What Claude and Gemini cost Designed Living, counted call by call (standard library only).

Every Claude call passes its response's `usage` to record(), and every Gemini call passes what Google reported to
record_gemini(): the tokens are added to `.usage.json` (git-ignored) under the day, the feature (plan, design,
photos) and the model that answered. summary() turns them into dollars for the Settings page. Prices are list
prices; the Anthropic Console and Google's billing stay the bill. Copied from Jarvis 2.0's usage.py.
"""
import datetime
import json
import os
import sys
import threading
from pathlib import Path

USAGE_FILE = Path(__file__).resolve().parent / ".usage.json"
KEEP_DAYS = 400

# $ per million tokens: input, output, cache read. A cache write costs CACHE_WRITE x input (5-minute cache).
PRICES = {
    "claude-fable-5-2": (8.0, 40.0, 0.20),
    "claude-fable-5-1": (10.0, 50.0, 0.25),
    "claude-opus-5-5": (4.0, 20.0, 0.20),
    "claude-opus-5": (5.0, 25.0, 0.50),
    "claude-opus-4-8": (5.0, 25.0, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0, 0.10),
    "claude-sonnet-5": (2.0, 10.0, 0.20),
    "claude-sonnet-4-6": (3.0, 15.0, 0.30),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-haiku-4-5": (1.0, 5.0, 0.10),
}
# Gemini, $ per million tokens: text in, text out, cache read, audio in, audio out. Google's paid-tier list prices
# as of 2026-10-07 (the 3.8 rates are introductory until 2026-12-31 and double on 2027-01-01). Live bills every turn
# for the whole conversation so far, which is what its usage reports, so a long conversation costs more per turn.
GEMINI_PRICES = {
    "gemini-3.1-flash-live": (0.75, 4.50, 0.075, 3.00, 12.00),    # Live: conversations and read-aloud lines
    "gemini-3.8-flash-tts": (0.50, 9.00, 0.05, 0.50, 9.00),       # whole-line voice (the fallback, the greeting)
    "gemini-3.8-flash": (0.75, 3.75, 0.075, 1.50, 3.75),          # hearing Telegram voice notes (audio in: assumed)
    "gemini-2.5-flash-image": (0.30, 30.00, 0.03, 1.00, 30.00),   # wallpapers and room designs (about 4c a picture)
    "gemini-3-pro-image": (2.00, 120.00, 0.20, 2.00, 120.00),     # "Make it better" room designs (about 13c a picture)
    "gemini-embedding": (0.15, 0.00, 0.00, 0.15, 0.00),           # search by meaning (tokens estimated: meaning.py)
}
GEMINI_PRO_TEXT = (2.00, 12.00, 0.20, 2.00, 12.00)   # Gemini Pro text and pictures in (list price, up to 200k)
CACHE_WRITE = 1.25
SEARCH_USD = 0.01                       # per web search
FEATURES = {                            # what each feature is, in the user's words
    "plan": "Floor plans read (Claude measures, Gemini marks doors and furniture)",
    "design": "Room designs made from a plan (Nano Banana)",
    "photos": "Your own room photos redesigned (Nano Banana)",
}
TOOL_PREFIX = "mcp:"                     # an added tool's calls: feature = the tool server, model = mcp:<tool>
FIELDS = ("calls", "input", "output", "cache_read", "cache_write", "searches", "audio_in", "audio_out")

LOCK = threading.Lock()


def provider(model):
    model = model or ""
    return "gemini" if model.startswith("gemini") else "tool" if model.startswith(TOOL_PREFIX) else "claude"


def gemini_price(model):
    """Gemini's (text in, text out, cache read, audio in, audio out); an unknown model is priced like its kind."""
    model = model or ""
    for key in sorted(GEMINI_PRICES, key=len, reverse=True):
        if model.startswith(key):
            return GEMINI_PRICES[key]
    if "image" in model and "pro" in model:
        return GEMINI_PRICES["gemini-3-pro-image"]
    if "-pro" in model:                       # reading a floor plan picture (House Build)
        return GEMINI_PRO_TEXT
    kind = "live" if "live" in model or "audio" in model else "tts" if "tts" in model else \
        "image" if "image" in model else ""
    return next((v for k, v in GEMINI_PRICES.items() if kind and kind in k), GEMINI_PRICES["gemini-3.8-flash"])


def price(model):
    """(input, output, cache read) $ per million tokens; an unknown model is priced like the nearest family."""
    model = model or ""
    if model in PRICES:
        return PRICES[model]
    for key in sorted(PRICES, key=len, reverse=True):
        if model.startswith(key):
            return PRICES[key]
    return PRICES["claude-haiku-5-5" if "haiku" in model else "claude-fable-5-2" if "fable" in model
                  else "claude-sonnet-5-5" if "sonnet" in model else "claude-opus-5-5"]


def tokens_of(usage):
    """The counts from an API response's usage object (or a dict shaped like one)."""
    def get(obj, name):
        value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
        return value or 0
    tool = get(usage, "server_tool_use")
    return {"calls": 1, "input": get(usage, "input_tokens"), "output": get(usage, "output_tokens"),
            "cache_read": get(usage, "cache_read_input_tokens"),
            "cache_write": get(usage, "cache_creation_input_tokens"),
            "searches": get(tool, "web_search_requests") if tool else 0}


def gemini_tokens(usage, audio_out=False):
    """The counts from what Google reported, in any of its three shapes: the SDK's Live UsageMetadata
    (prompt_token_count, ...), generateContent's JSON usageMetadata (promptTokenCount, ...) and the Interactions
    API's Usage (total_input_tokens, ...). Thinking is billed as output and tool results as input. audio_out: the
    model only speaks, so output without a breakdown is audio."""
    def get(obj, *names):
        for name in names:
            value = obj.get(name) if isinstance(obj, dict) else getattr(obj, name, None)
            if value:
                return value
        return 0

    def audio(details):
        n = 0
        for d in details or []:
            if "AUDIO" in str(get(d, "modality")).upper():
                n += get(d, "token_count", "tokenCount", "tokens")
        return n
    prompt = get(usage, "prompt_token_count", "promptTokenCount", "total_input_tokens")
    cached = get(usage, "cached_content_token_count", "cachedContentTokenCount", "total_cached_tokens")
    tools = get(usage, "tool_use_prompt_token_count", "toolUsePromptTokenCount", "total_tool_use_tokens")
    answer = get(usage, "response_token_count", "candidates_token_count", "candidatesTokenCount",
                 "responseTokenCount", "total_output_tokens")
    thoughts = get(usage, "thoughts_token_count", "thoughtsTokenCount", "total_thought_tokens")
    out_details = get(usage, "response_tokens_details", "candidates_tokens_details", "candidatesTokensDetails",
                      "responseTokensDetails", "output_tokens_by_modality")
    audio_in = audio(get(usage, "prompt_tokens_details", "promptTokensDetails", "input_tokens_by_modality")) \
        - audio(get(usage, "cache_tokens_details", "cacheTokensDetails", "cached_tokens_by_modality"))
    fresh_in = max(0, prompt - cached) + tools
    return {"calls": 1, "input": fresh_in, "output": answer + thoughts, "cache_read": cached, "cache_write": 0,
            "searches": 0, "audio_in": min(fresh_in, max(0, audio_in)),
            "audio_out": audio(out_details) if out_details else answer if audio_out else 0}


def cost(model, t):
    t = {**dict.fromkeys(FIELDS, 0), **t}
    if provider(model) == "tool":
        return 0.0                          # nothing is paid per call; the Live turn or job that asked is counted
    if provider(model) == "gemini":
        p_in, p_out, p_read, p_ain, p_aout = gemini_price(model)
        return ((t["input"] - t["audio_in"]) * p_in + t["audio_in"] * p_ain + (t["output"] - t["audio_out"]) * p_out
                + t["audio_out"] * p_aout + t["cache_read"] * p_read) / 1e6
    p_in, p_out, p_read = price(model)
    return (t["input"] * p_in + t["output"] * p_out + t["cache_read"] * p_read
            + t["cache_write"] * p_in * CACHE_WRITE) / 1e6 + t["searches"] * SEARCH_USD


def load():
    try:
        data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data.get("days"), dict) else {"days": {}}
    except (OSError, ValueError, AttributeError):
        return {"days": {}}


def record(feature, model, usage, day=None):
    """Add one Claude response's usage. Never raises: counting must not break an answer."""
    add(feature, model, lambda: tokens_of(usage), day)


def record_gemini(feature, model, usage, audio_out=False, day=None):
    """Add what Google reported for one Gemini request (or one Live turn). Nothing reported, nothing added."""
    if usage:
        add(feature, model, lambda: gemini_tokens(usage, audio_out), day)


def record_tool(server, tool, day=None):
    """One call to an added tool (an MCP server's), counted under the server's name."""
    add(server, TOOL_PREFIX + tool, lambda: {"calls": 1}, day)


def add(feature, model, counts, day=None):
    try:
        t = counts()
        day = day or datetime.date.today().isoformat()
        with LOCK:
            data = load()
            days = data["days"]
            row = days.setdefault(day, {}).setdefault(f"{feature}|{model}", dict.fromkeys(FIELDS, 0))
            for k in FIELDS:
                row[k] = row.get(k, 0) + t.get(k, 0)
            for old in sorted(days)[:-KEEP_DAYS]:
                del days[old]
            tmp = USAGE_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
            os.replace(tmp, USAGE_FILE)
    except Exception as exc:
        print(f"usage: couldn't record a {feature} call: {exc}", file=sys.stderr, flush=True)


def total(rows):
    out = {"usd": 0.0, **dict.fromkeys(FIELDS, 0)}
    for (_, model), t in rows:
        out["usd"] += cost(model, t)
        for k in FIELDS:
            out[k] += t.get(k, 0)
    return out


def period(days, first, last, who="claude"):
    """One provider's totals for the days first..last (ISO dates, inclusive), split by feature and by model."""
    rows = [(tuple(key.split("|", 1)), t) for day, keyed in days.items() if first <= day <= last
            for key, t in keyed.items() if "|" in key and provider(key.split("|", 1)[1]) == who]
    out = total(rows)
    by = lambda i: {name: total([r for r in rows if r[0][i] == name]) for name in sorted({r[0][i] for r in rows})}
    out["features"] = sorted(({"feature": f, "label": FEATURES.get(f, f), **v} for f, v in by(0).items()),
                             key=lambda v: -v["usd"])
    out["models"] = sorted(({"model": m, **v} for m, v in by(1).items()), key=lambda v: -v["usd"])
    paid_in = sum(cost(m, {**dict.fromkeys(FIELDS, 0), "input": t["input"], "cache_read": t["cache_read"],
                           "cache_write": t["cache_write"], "audio_in": t.get("audio_in", 0)})
                  for (_, m), t in rows)
    out["input_share"] = round(paid_in / out["usd"], 3) if out["usd"] else 0
    return out


def periods(days, today, who):
    iso = lambda d: d.isoformat()
    yesterday = today - datetime.timedelta(days=1)
    seen = [day for day, keyed in days.items() if any(provider(k.split("|", 1)[-1]) == who for k in keyed)]
    return {
        "since": min(seen) if seen else None,
        "today": period(days, iso(today), iso(today), who),
        "yesterday": period(days, iso(yesterday), iso(yesterday), who),
        "week": period(days, iso(today - datetime.timedelta(days=6)), iso(today), who),
        "month": period(days, iso(today.replace(day=1)), iso(today), who),
        "daily": [{"day": iso(today - datetime.timedelta(days=i)),
                   "usd": round(period(days, iso(today - datetime.timedelta(days=i)),
                                       iso(today - datetime.timedelta(days=i)), who)["usd"], 4)}
                  for i in range(29, -1, -1)],
    }


def summary(today=None):
    """Claude's periods at the top level (as before), Gemini's under "gemini"."""
    today = today or datetime.date.today()
    days = load()["days"]
    return {
        "prices": {m: {"input": p[0], "output": p[1], "cache_read": p[2]} for m, p in PRICES.items()},
        **periods(days, today, "claude"),
        "gemini": {
            "prices": {m: {"input": p[0], "output": p[1], "cache_read": p[2], "audio_in": p[3], "audio_out": p[4]}
                       for m, p in GEMINI_PRICES.items()},
            **periods(days, today, "gemini"),
        },
        "tools": periods(days, today, "tool"),
    }
