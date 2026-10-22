"""Shared look-and-feel helpers: brand palette, colored KPI tiles, cards and badges.

Colors and fonts come from .streamlit/config.toml. Native theming cannot color
individual metric tiles, so a single CSS block styles keyed KPI containers only
(selectors match the `st-key-kpi_<color>_...` classes Streamlit adds for keys).
"""

import re
from contextlib import contextmanager

import streamlit as st

# Accent colors by meaning: blue = revenue, violet = orders, teal = order value/customers, orange = freight,
# red = late/negative, green = on-time/satisfaction, navy = neutral highlights.
PALETTE = {
    "blue": "#29B5E8",
    "navy": "#11567F",
    "violet": "#6554C0",
    "teal": "#00A3BF",
    "orange": "#FF8B00",
    "green": "#36B37E",
    "red": "#DE350B",
    "amber": "#FFAB00",
    "grey": "#8A9BA8",
}
# Light background tints drawn behind KPI tiles of the matching accent color.
TINTS = {
    "blue": "#EAF7FD",
    "navy": "#E8EFF4",
    "violet": "#F0EEFA",
    "teal": "#E6F7FA",
    "orange": "#FFF4E6",
    "green": "#EAF7F1",
    "red": "#FDEDEA",
    "amber": "#FFF8E6",
    "grey": "#F2F5F7",
}
# Ordered palette for multi-series charts (matches chartCategoricalColors in config.toml).
SERIES = [PALETTE[c] for c in ("blue", "violet", "teal", "orange", "green", "red", "navy", "amber")]
# Sequential scales used for "bad is high" and "good is high" encodings.
SCALE_BAD = ["#FDEDEA", "#F7A58F", "#DE350B", "#8F1F05"]
SCALE_GOOD = ["#DE350B", "#FFAB00", "#9CD4B8", "#36B37E"]


def _css() -> str:
    """Build one <style> block: for each color, a tinted background, accent border and label style for
    containers whose key starts with kpi_<color>_.
    """
    rules = []
    for name, accent in PALETTE.items():
        sel = f'[class*="st-key-kpi_{name}_"]'
        rules.append(
            f"{sel} {{ background: {TINTS[name]}; border: 1px solid {accent}33; border-left: 5px solid {accent};"
            f" border-radius: 10px; padding: 0.75rem 1rem 0.5rem 1rem; }}"
            f"{sel} [data-testid='stMetricLabel'] p {{ color: {accent}; font-weight: 600; text-transform: uppercase;"
            f" letter-spacing: 0.03em; font-size: 0.74rem; }}"
            f"{sel} [data-testid='stMetricValue'] {{ color: #1B2B3A; font-weight: 700; }}"
        )
    return "<style>" + "".join(rules) + "</style>"


def inject_css():
    """Inject the KPI tile CSS (called once per run from streamlit_app.py)."""
    st.html(_css())


def _slug(text: str) -> str:
    """Turn a label into a lowercase, key-safe slug for container keys."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def kpi_tile(label, value, color="blue", icon=None, help=None, delta=None, delta_color="normal",
             chart_data=None, chart_type="bar", key=None):
    """Render one colored KPI tile. The container key kpi_<color>_<slug> is what the CSS targets, so labels
    must be unique on a page (or pass key=).
    """
    color = color if color in PALETTE else "blue"
    with st.container(key=f"kpi_{color}_{key or _slug(label)}"):
        st.metric(
            f"{icon} {label}" if icon else label,
            value,
            delta=delta,
            delta_color=delta_color,
            help=help,
            chart_data=chart_data,
            chart_type=chart_type,
            border=False,
        )


def kpi_row(tiles: list):
    """tiles: list of kwargs dicts for kpi_tile."""
    with st.container(horizontal=True, gap="small"):
        for tile in tiles:
            kpi_tile(**tile)


@contextmanager
def card(title: str, icon: str = None, caption: str = None):
    """Bordered card with a heading and optional caption; use as `with ui.card(...):`."""
    with st.container(border=True):
        st.markdown(f"#### {icon + ' ' if icon else ''}{title}")
        if caption:
            st.caption(caption)
        yield


def page_intro(text: str):
    """Short grey description shown under the page title."""
    st.caption(text)


def scope_badges(start, end, states, extra: list = None):
    """Header badges for the data source, the active date range and the selected states."""
    parts = [
        ":blue-badge[:material/database: ECOMMERCE_DB.STAGING]",
        f":violet-badge[:material/calendar_month: {start} → {end}]",
        f":green-badge[:material/map: {', '.join(states) if states else 'All states'}]",
    ]
    for item in extra or []:
        parts.append(item)
    st.markdown(" ".join(parts))
