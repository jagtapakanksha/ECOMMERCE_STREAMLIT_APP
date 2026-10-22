import streamlit as st

import agent
import data

MSGS = "assistant_messages"
PENDING = "assistant_pending"
USER_AVATAR = ":material/person:"
AGENT_AVATAR = ":material/smart_toy:"
PERIOD_OPTIONS = ["Full history", *[p for p in data.PERIODS if data.PERIODS[p]], "Dashboard date range"]
SCOPE_DEFAULTS = {
    "scope_focus": agent.ALL_TOPICS,
    "scope_period": "Full history",
    "scope_states": [],
    "scope_category": agent.ALL_CATEGORIES,
    "scope_style": "Detailed",
}

st.session_state.setdefault(MSGS, [])
# Widget state is dropped when the user visits another page, so keep a copy to restore the scope on return.
for _key, _value in SCOPE_DEFAULTS.items():
    st.session_state.setdefault(_key, st.session_state.get(f"_saved_{_key}", _value))


def queue_question(question: str):
    st.session_state[PENDING] = question


def pick_starter():
    choice = st.session_state.get("assistant_starter")
    st.session_state["assistant_starter"] = None
    if choice:
        queue_question(choice)


def clear_conversation():
    st.session_state[MSGS] = []
    st.session_state.pop(PENDING, None)


def reset_scope():
    for key, value in SCOPE_DEFAULTS.items():
        st.session_state[key] = list(value) if isinstance(value, list) else value


def history_for_agent(messages: list) -> list:
    """Completed user/assistant pairs only, so failed turns are not replayed to the agent."""
    history = []
    for i in range(0, len(messages) - 1, 2):
        user, answer = messages[i], messages[i + 1]
        if answer.get("text") and not answer.get("error"):
            history.append({"role": "user", "text": user["sent"]})
            history.append({"role": "assistant", "text": answer["text"]})
    return history


def render_user(msg: dict):
    st.markdown(agent.escape_markdown_dollars(msg["text"]))
    if msg.get("badges"):
        st.markdown(" ".join(msg["badges"]))


def render_answer(msg: dict, idx: int, is_last: bool):
    if msg.get("error"):
        st.error(f"The agent could not answer: {msg['error']}", icon=":material/error:")
    if msg.get("text"):
        st.markdown(agent.escape_markdown_dollars(msg["text"]))
    for chart in msg.get("charts", []):
        try:
            st.vega_lite_chart(chart, width="stretch")
        except Exception:
            pass
    for err in msg.get("tool_errors", []):
        st.warning(f"Tool issue: {err}", icon=":material/warning:")

    queries = msg.get("queries", [])
    if queries:
        label = f"Data behind this answer ({len(queries)} {'query' if len(queries) == 1 else 'queries'})"
        with st.expander(label, icon=":material/table_view:"):
            for n, q in enumerate(queries, start=1):
                badge = " :green-badge[:material/verified: verified query]" if q.get("verified_query_used") else ""
                st.markdown(f"**Query {n}** · {len(q['df'])} row(s){badge}")
                st.code(q["sql"], language="sql")
                st.dataframe(q["df"], hide_index=True, width="stretch")

    meta = [f":material/timer: {msg.get('elapsed', 0):.0f}s"]
    if msg.get("query_id"):
        meta.append(f"query ID {msg['query_id']}")
    st.caption(" · ".join(meta))

    if is_last and msg.get("suggestions"):
        st.caption("Suggested follow-ups")
        with st.container(horizontal=True, gap="small"):
            for j, suggestion in enumerate(msg["suggestions"][:4]):
                st.button(suggestion, key=f"assistant_suggestion_{idx}_{j}", on_click=queue_question,
                          args=(suggestion,), icon=":material/subdirectory_arrow_right:", type="tertiary")


messages = st.session_state[MSGS]

st.caption(
    "Ask any question in plain language. The Cortex Agent writes and runs SQL against the ECOMMERCE_SV "
    "semantic view and explains the result."
)

# ----------------------------------------------------------------- question scope panel
with st.spinner("Loading scope options..."):
    state_options = data.load_states()
    category_options = data.load_category_options()

with st.container(border=True):
    st.markdown("#### :material/tune: Question scope")
    with st.container(horizontal=True, gap="small"):
        focus = st.selectbox("Focus area", list(agent.FOCUS_QUESTIONS), key="scope_focus",
                             help="Steers the agent and changes the suggested questions.")
        period_label = st.selectbox("Time period", PERIOD_OPTIONS, key="scope_period",
                                    help="'Dashboard date range' uses the period chosen in the sidebar.")
        scope_states = st.multiselect("Customer states", state_options, key="scope_states", placeholder="All states")
        category = st.selectbox("Product category", [agent.ALL_CATEGORIES, *category_options], key="scope_category")
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        style = st.segmented_control("Answer style", ["Detailed", "Executive summary"], key="scope_style",
                                     width="content") or "Detailed"
        st.space("stretch")
        st.button("Reset scope", icon=":material/restart_alt:", on_click=reset_scope, key="assistant_reset_scope")
        st.button("Clear chat", icon=":material/delete_sweep:", on_click=clear_conversation,
                  disabled=not messages, key="assistant_clear")

if period_label == "Dashboard date range":
    f_start, f_end, _ = data.filters()
    period = (f_start, f_end)
else:
    period = data.PERIODS.get(period_label)
for _key in SCOPE_DEFAULTS:
    st.session_state[f"_saved_{_key}"] = st.session_state[_key]
scope_text, scope_badges = agent.build_scope(focus, period_label, period, sorted(scope_states), category, style)
if scope_badges:
    st.markdown("**Active scope:** " + " ".join(scope_badges))
else:
    st.caption(":material/public: No scope applied: the agent answers over all available data.")

# ----------------------------------------------------------------- conversation
# Read the input first so the previous answer's follow-ups are hidden while a new question runs.
typed = st.chat_input("Ask the E-Commerce Intelligence agent...")
prompt = typed or st.session_state.pop(PENDING, None)

if not messages and not prompt:
    with st.chat_message("assistant", avatar=AGENT_AVATAR):
        st.markdown(
            "Hi, I'm the **E-Commerce Intelligence** agent. I can analyse sales, customers, products, "
            "delivery performance, reviews and anomalies in the Olist data. Pick a question below or type your own."
        )
        st.pills("Try asking", agent.FOCUS_QUESTIONS[focus], key="assistant_starter", on_change=pick_starter,
                 label_visibility="collapsed")

for idx, msg in enumerate(messages):
    with st.chat_message(msg["role"], avatar=USER_AVATAR if msg["role"] == "user" else AGENT_AVATAR):
        if msg["role"] == "user":
            render_user(msg)
        else:
            render_answer(msg, idx, is_last=idx == len(messages) - 1 and not prompt)

if prompt:
    sent = f"{prompt}\n\n{scope_text}" if scope_text else prompt
    history = history_for_agent(messages)

    user_msg = {"role": "user", "text": prompt, "sent": sent, "badges": scope_badges}
    messages.append(user_msg)
    with st.chat_message("user", avatar=USER_AVATAR):
        render_user(user_msg)

    with st.chat_message("assistant", avatar=AGENT_AVATAR):
        with st.spinner("The agent is analysing the data. This usually takes 15-60 seconds..."):
            answer = agent.ask_agent(history, sent)
        answer["role"] = "assistant"
        messages.append(answer)
        render_answer(answer, len(messages) - 1, is_last=True)

st.caption(
    "Answers are generated by an AI agent from ECOMMERCE_DB data. Check the SQL and data behind each answer "
    "before acting on it."
)
