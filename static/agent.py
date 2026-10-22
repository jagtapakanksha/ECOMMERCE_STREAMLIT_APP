"""Client for the ECOMMERCE_INTELLIGENCE_AGENT Cortex Agent.

Calls SNOWFLAKE.CORTEX.DATA_AGENT_RUN through the app's Snowflake connection.
The agent name and the JSON request body are bound parameters, so user text is
never concatenated into SQL. Agent calls go through a cursor (not conn.query)
so every question runs fresh instead of being served from the query cache.
"""

import json
import time

import pandas as pd

import data

# Agent to call, how many prior chat messages to replay, and the SQL timeout for one agent run.
AGENT_FQN = "ECOMMERCE_DB.ANALYTICS.ECOMMERCE_INTELLIGENCE_AGENT"
MAX_HISTORY_MESSAGES = 10
TIMEOUT_SECONDS = 600

# Mirrors instructions.sample_questions in the agent spec.
SAMPLE_QUESTIONS = [
    "What was our monthly product revenue?",
    "Which ten product categories generated the most revenue?",
    "Which Brazilian states generated the highest sales?",
    "What percentage of delivered orders arrived late?",
    "Which sellers have the highest late-delivery rates?",
    "Which product categories have the lowest average review scores?",
    "What is the average order value?",
    "Which payment methods contribute the most payment value?",
    "What unusual revenue patterns can you identify?",
    "How can we improve delivery performance and customer satisfaction?",
]

# Result-set column types (from the Agent API rowType metadata) that are converted to numbers.
NUMERIC_TYPES = {"fixed", "real", "number", "float", "double", "decimal"}


def build_request(history: list, question: str) -> dict:
    """history: prior chat turns as {"role": "user"|"assistant", "text": str}."""
    # The Agent API expects each message as a role plus a list of typed content blocks; only the most recent
    # messages are replayed.
    messages = [
        {"role": m["role"], "content": [{"type": "text", "text": m["text"]}]}
        for m in history[-MAX_HISTORY_MESSAGES:]
        if m.get("text")
    ]
    messages.append({"role": "user", "content": [{"type": "text", "text": question}]})
    return {"messages": messages}


def _result_set_to_df(result_set: dict) -> pd.DataFrame:
    """Convert an Analyst result_set (rowType metadata + rows of strings) into a typed DataFrame."""
    meta = (result_set or {}).get("resultSetMetaData", {}) or {}
    row_type = meta.get("rowType", []) or []
    columns = [c.get("name", f"col_{i}") for i, c in enumerate(row_type)]
    rows = (result_set or {}).get("data", []) or []
    if not columns and rows:
        columns = [f"col_{i}" for i in range(len(rows[0]))]
    df = pd.DataFrame(rows, columns=columns)
    for col_meta in row_type:
        name = col_meta.get("name")
        if name in df.columns and str(col_meta.get("type", "")).lower() in NUMERIC_TYPES:
            df[name] = pd.to_numeric(df[name], errors="coerce")
    return df


def parse_response(resp: dict) -> dict:
    """Split an agent response into answer text, executed queries, charts and suggestions."""
    texts, queries, charts, suggestions, tool_errors = [], [], [], [], []
    for item in resp.get("content", []) or []:
        kind = item.get("type")
        if kind == "text":
            texts.append(item.get("text", ""))
        # Cortex Analyst tool results carry the generated SQL and its result_set; other tool results are
        # ignored.
        elif kind == "tool_result":
            result = item.get("tool_result", {}) or {}
            if str(result.get("status", "success")).lower() not in ("success", "completed"):
                tool_errors.append(f"{result.get('name', 'tool')}: {result.get('status')}")
            for part in result.get("content", []) or []:
                payload = part.get("json") if part.get("type") == "json" else None
                if isinstance(payload, dict) and payload.get("sql"):
                    queries.append({
                        "sql": payload["sql"],
                        "df": _result_set_to_df(payload.get("result_set")),
                        "verified_query_used": bool(payload.get("verified_query_used")),
                        "query_id": payload.get("query_id"),
                    })
        # Chart items hold a Vega-Lite spec (often as a JSON string) when the agent produces a chart.
        elif kind == "chart":
            spec = (item.get("chart", {}) or {}).get("chart_spec")
            if isinstance(spec, str):
                try:
                    spec = json.loads(spec)
                except ValueError:
                    spec = None
            if isinstance(spec, dict):
                charts.append(spec)
        # Follow-up questions suggested by the agent; shown as buttons under the latest answer.
        elif kind == "suggested_queries":
            for s in item.get("suggested_queries", []) or []:
                q = s.get("query") if isinstance(s, dict) else s
                if q:
                    suggestions.append(q)
    return {
        "text": "\n\n".join(t for t in texts if t).strip(),
        "queries": queries,
        "charts": charts,
        "suggestions": suggestions,
        "status": resp.get("status"),
        "tool_errors": tool_errors,
    }


def ask_agent(history: list, question: str) -> dict:
    """Run the agent and return the parsed answer plus run metadata. Never raises."""
    body = json.dumps(build_request(history, question))
    started = time.time()
    query_id = None
    try:
        # Use a cursor rather than conn.query: conn.query always caches, and every question must run fresh.
        cur = data.get_conn().cursor()
        cur.execute(
            "SELECT SNOWFLAKE.CORTEX.DATA_AGENT_RUN(?, ?)",
            [AGENT_FQN, body],
            timeout=TIMEOUT_SECONDS,
        )
        query_id = cur.sfqid
        raw = cur.fetchone()[0]
        resp = json.loads(raw) if isinstance(raw, str) else raw
        resp = resp or {}
        if resp.get("code") and "content" not in resp:
            # Agent API errors come back as {"code", "message", "request_id"} instead of raising.
            request_id = resp.get("request_id")
            error = f"{resp.get('message', 'Unknown agent error')} (code {resp['code']}"
            error += f", request ID {request_id})" if request_id else ")"
            parsed = {"text": "", "queries": [], "charts": [], "suggestions": [], "status": "error",
                      "tool_errors": [], "error": error}
        else:
            parsed = parse_response(resp)
            if parsed["status"] not in (None, "completed"):
                parsed["error"] = f"Agent run ended with status '{parsed['status']}'."
            elif not parsed["text"]:
                parsed["error"] = "The agent returned no answer text."
    except Exception as exc:  # surface any SQL/agent error in the chat instead of crashing the page
        parsed = {"text": "", "queries": [], "charts": [], "suggestions": [], "status": "error",
                  "tool_errors": [], "error": str(exc)}
    parsed["query_id"] = query_id
    parsed["elapsed"] = time.time() - started
    return parsed


def build_scope(focus: str, period_label: str, period, states, category: str, style: str):
    """Turn the page's scope dropdowns into (instruction text for the agent, display badges).

    Returns ("", []) when every control is at its default, so the question is sent unchanged.
    """
    parts, badges = [], []
    if period:
        parts.append(f"purchases from {period[0]} to {period[1]}")
        badges.append(f":violet-badge[:material/calendar_month: {period_label}: {period[0]} → {period[1]}]")
    if states:
        parts.append(f"customer states {', '.join(states)}")
        badges.append(f":green-badge[:material/map: {', '.join(states)}]")
    if category and category != ALL_CATEGORIES:
        parts.append(f"product category '{category}'")
        badges.append(f":orange-badge[:material/category: {category}]")
    if focus and focus != ALL_TOPICS:
        parts.append(f"focus area {focus}")
        badges.append(f":blue-badge[:material/center_focus_strong: {focus}]")
    text = ""
    if parts:
        text = f"(Question scope, apply unless my question says otherwise: {'; '.join(parts)}.)"
    if style == "Executive summary":
        text = (text + " " if text else "") + (
            "(Answer as a short executive summary: 3-5 bullet points with the key numbers, "
            "then one recommendation and one limitation.)")
        badges.append(":gray-badge[:material/short_text: Executive summary]")
    return text, badges


# Dropdown values that mean 'no filter' on the agent page.
ALL_TOPICS = "All topics"
ALL_CATEGORIES = "All categories"
# Starter questions shown on the agent page for each focus area.
FOCUS_QUESTIONS = {
    ALL_TOPICS: SAMPLE_QUESTIONS,
    "Sales & revenue": [
        "What was our monthly product revenue?",
        "Which Brazilian states generated the highest sales?",
        "What is the average order value?",
        "How did product revenue in 2018 compare with 2017?",
    ],
    "Customers": [
        "How many unique customers do we have and what share are repeat buyers?",
        "Which states have the most customers?",
        "How concentrated is revenue among the top 10% of customers?",
    ],
    "Products & categories": [
        "Which ten product categories generated the most revenue?",
        "Which categories have the highest freight relative to item price?",
        "Which categories have the highest average item price?",
    ],
    "Delivery & sellers": [
        "What percentage of delivered orders arrived late?",
        "Which sellers have the highest late-delivery rates?",
        "Which customer states have the slowest deliveries?",
    ],
    "Satisfaction": [
        "Which product categories have the lowest average review scores?",
        "How do review scores differ for late versus on-time deliveries?",
        "What share of reviews are 1 or 2 stars?",
    ],
    "Anomalies": [
        "What unusual revenue patterns can you identify?",
        "Which months had unusual late-delivery rates?",
        "Were there months where review scores dropped sharply?",
    ],
}


def escape_markdown_dollars(text: str) -> str:
    """Stop Streamlit from rendering 'R$ 1 ... R$ 2' as LaTeX."""
    return text.replace("\\$", "$").replace("$", "\\$")
