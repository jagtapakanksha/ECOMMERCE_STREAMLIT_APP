"""E-Commerce Intelligence: Streamlit in Snowflake app over ECOMMERCE_DB (Olist Brazilian marketplace).

This entry script runs on every rerun, before the selected page:
  1. reloads the helper modules if they changed on disk,
  2. sets the page config, theme CSS and the shared Snowflake connection,
  3. builds the top navigation (six dashboards + the Cortex Agent chat),
  4. renders the sidebar filters and stores them in st.session_state (f_start, f_end, f_states),
  5. renders the page header and runs the selected page from app_pages/.

Pages read the filters through data.filters(); all queries live in data.py, agent calls in agent.py
and shared styling helpers in ui.py.
"""

import importlib
import os

import streamlit as st

import agent
import data
import ui


def _fresh(module):
    """Reload a helper module if its file changed since it was imported.

    The app process survives between Runs, so without this an edited data.py/ui.py/agent.py
    can stay stale in memory while the pages already use its new names.
    """
    mtime = os.path.getmtime(module.__file__)
    if getattr(module, "_loaded_mtime", None) != mtime:
        module = importlib.reload(module)
        module._loaded_mtime = mtime
    return module

# Order matters: agent imports data, so reload data first.
data = _fresh(data)
ui = _fresh(ui)
agent = _fresh(agent)

# Page config must be the first Streamlit call. The KPI tile CSS is injected once per run for every page.
st.set_page_config(page_title="E-Commerce Intelligence", page_icon=":material/insights:", layout="wide")
ui.inject_css()

# Embedded Snowflake connection (shared by every page through data.get_conn()).
conn = st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))

# Top navigation, grouped into dashboards and AI. Each st.Page points to a script in app_pages/.
page = st.navigation(
    {
        "Dashboards": [
            st.Page("app_pages/overview.py", title="Overview", icon=":material/dashboard:", default=True),
            st.Page("app_pages/sales.py", title="Sales & Products", icon=":material/storefront:"),
            st.Page("app_pages/customers.py", title="Customers", icon=":material/group:"),
            st.Page("app_pages/delivery.py", title="Delivery & Sellers", icon=":material/local_shipping:"),
            st.Page("app_pages/satisfaction.py", title="Satisfaction", icon=":material/reviews:"),
            st.Page("app_pages/anomalies.py", title="Anomalies", icon=":material/troubleshoot:"),
        ],
        "AI": [
            st.Page("app_pages/assistant.py", title="Ask the Agent", icon=":material/smart_toy:"),
        ],
    },
    position="top",
)
# The agent page has its own scope panel, so the sidebar shows a hint and the header shows agent badges there.
is_agent_page = page.title == "Ask the Agent"

# ----------------------------------------------------------------- sidebar filters
with st.sidebar:
    st.markdown("### :material/insights: E-Commerce Intelligence")
    st.caption("Olist Brazilian marketplace analytics")

    # Date bounds and the state list come from STAGING (cached for 30 minutes by data._run).
    with st.spinner("Loading filter options..."):
        bounds = data.load_date_bounds().iloc[0]
        all_states = data.load_states()
    min_date, max_date = bounds["min_date"], bounds["max_date"]

    st.markdown("#### :material/tune: Dashboard filters")
    if is_agent_page:
        st.caption("These filters drive the dashboards. Use the question scope panel on this page for the agent.")

    # Named presets come from data.PERIODS; 'All data' maps to None and uses the full data range. 'Custom
    # range' shows a date picker instead.
    preset = st.selectbox("Period", [*data.PERIODS, "Custom range"], key="w_period",
                          help="Core period excludes the sparse months in 2016 and Sep–Oct 2018.")
    if preset == "Custom range":
        picked = st.date_input(
            "Purchase date range",
            value=(max(data.DEFAULT_START, min_date), min(data.DEFAULT_END, max_date)),
            min_value=min_date,
            max_value=max_date,
            key="w_dates",
        )
        if isinstance(picked, (tuple, list)) and len(picked) == 2:
            f_start, f_end = picked
        else:
            # Range selection in progress: keep the last complete range.
            f_start = st.session_state.get("f_start", data.DEFAULT_START)
            f_end = st.session_state.get("f_end", data.DEFAULT_END)
    else:
        f_start, f_end = data.PERIODS[preset] or (min_date, max_date)

    f_states = st.multiselect("Customer state", all_states, default=[], key="w_states", placeholder="All states")

    # Publish the resolved filters in session state; every dashboard page reads them via data.filters().
    st.session_state["f_start"] = f_start
    st.session_state["f_end"] = f_end
    st.session_state["f_states"] = sorted(f_states)

    # Clears every cached query result so the next run reloads from Snowflake.
    st.button("Refresh data", icon=":material/refresh:", on_click=data.clear_cache, width="stretch",
              help="Clear cached query results and reload from Snowflake.")

    with st.expander("Metric definitions", icon=":material/menu_book:"):
        st.markdown(
            "- **Product revenue** = SUM(PRICE), excluding freight\n"
            "- **Freight** = SUM(FREIGHT_VALUE)\n"
            "- **AOV** = product revenue ÷ orders with items\n"
            "- **Late** = delivered after the estimated date (delivered orders only)\n"
            "- **Customers** = distinct CUSTOMER_UNIQUE_ID\n"
            "- All amounts in BRL (R\\$)"
        )

# ----------------------------------------------------------------- header
# Page title plus context badges (data source, period, states or the agent and semantic view).
with st.container(horizontal=True, vertical_alignment="center"):
    st.title(f"{page.icon} {page.title}", width="content")
    st.space("small")
    if is_agent_page:
        st.markdown(":blue-badge[:material/smart_toy: ECOMMERCE_INTELLIGENCE_AGENT] "
                    ":violet-badge[:material/schema: ECOMMERCE_SV semantic view]")
    else:
        ui.scope_badges(f_start, f_end, sorted(f_states))

# Render the selected page below the shared header.
page.run()
