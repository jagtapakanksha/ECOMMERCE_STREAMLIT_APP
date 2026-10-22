import altair as alt
import streamlit as st

import data
import ui

start, end, states = data.filters()

# Fixed allowlist: UI label -> (column, default threshold %, higher_is_bad)
METRICS = {
    "Product revenue": ("product_revenue", 25, False),
    "Orders": ("orders", 25, False),
    "Average order value": ("aov", 10, False),
    "Late delivery rate": ("late_rate", 50, True),
    "Avg review score": ("avg_review_score", 5, False),
}
THRESHOLDS = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100]

with st.spinner("Loading monthly data..."):
    monthly = data.load_monthly(start, end, states)

if monthly.empty:
    st.info("No orders match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("Months that deviate sharply from their recent baseline. Flags show where to look, not why it happened.")

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        label = st.segmented_control("Metric", list(METRICS), default="Product revenue",
                                     key="anom_metric") or "Product revenue"
        col, default_thr, higher_is_bad = METRICS[label]
        window = st.selectbox("Baseline months", [2, 3, 4, 6], index=1, key="anom_window", width=140)
        threshold = st.selectbox("Flag at ± %", THRESHOLDS, index=THRESHOLDS.index(default_thr),
                                 key=f"anom_thr_{col}", width=120)
        min_orders = st.selectbox("Min orders / month", [0, 100, 250, 500, 1000], index=3, key="anom_min_orders",
                                  width=160, help="Months below this volume are excluded as too sparse.")

eligible = monthly[monthly["orders"] >= min_orders].reset_index(drop=True)
if eligible.empty:
    st.info(f"No month has at least {min_orders} orders in the current selection.", icon=":material/info:")
    st.stop()
m = eligible[["month", "orders"]].copy()
m["value"] = eligible[col]
m["baseline"] = m["value"].shift(1).rolling(int(window), min_periods=int(window)).mean()
m["deviation"] = (m["value"] - m["baseline"]) / m["baseline"]
m["flag"] = m["deviation"].abs() >= threshold / 100
m["direction"] = m["deviation"].map(lambda d: "Above baseline" if d > 0 else "Below baseline")
m["impact"] = m.apply(lambda r: "Favourable" if (r["deviation"] > 0) != higher_is_bad else "Unfavourable", axis=1)

flagged = m[m["flag"]].sort_values("month")
is_pct = col == "late_rate"
value_fmt = ".1%" if is_pct else (",.2f" if col in ("aov", "avg_review_score", "product_revenue") else ",")


def month_label(row):
    return f"{row['month']:%b %Y} · {row['deviation']:+.1%}"


spike = m.loc[m["deviation"].idxmax()] if m["deviation"].notna().any() else None
drop = m.loc[m["deviation"].idxmin()] if m["deviation"].notna().any() else None
ui.kpi_row([
    dict(label="Flagged months", value=str(len(flagged)), color="red" if len(flagged) else "green",
         icon=":material/flag:", help=f"Months deviating by {threshold}% or more from the baseline."),
    dict(label="Largest increase", value=month_label(spike) if spike is not None else "–",
         color="red" if higher_is_bad else "green", icon=":material/trending_up:", key="largest_increase"),
    dict(label="Largest decrease", value=month_label(drop) if drop is not None else "–",
         color="green" if higher_is_bad else "red", icon=":material/trending_down:", key="largest_decrease"),
    dict(label="Months analysed", value=str(len(m)), color="blue", icon=":material/calendar_month:",
         help=f"{len(monthly) - len(m)} sparse month(s) excluded."),
])

with ui.card(f"{label}: actual vs trailing {int(window)}-month average", ":material/show_chart:"):
    base = alt.Chart(m).encode(x=alt.X("yearmonth(month):T", title=None))
    band = base.mark_area(opacity=0.12, color=ui.PALETTE["grey"]).encode(
        y=alt.Y("baseline_low:Q"), y2="baseline_high:Q"
    ).transform_calculate(
        baseline_low=f"datum.baseline * (1 - {threshold / 100})",
        baseline_high=f"datum.baseline * (1 + {threshold / 100})",
    )
    actual = base.mark_line(point=True, color=ui.PALETTE["blue"], strokeWidth=2.5).encode(
        y=alt.Y("value:Q", title=label, scale=alt.Scale(zero=False),
                axis=alt.Axis(format="%" if is_pct else "~s")),
        tooltip=[
            alt.Tooltip("yearmonth(month):T", title="Month"),
            alt.Tooltip("value:Q", title="Actual", format=value_fmt),
            alt.Tooltip("baseline:Q", title="Baseline", format=value_fmt),
            alt.Tooltip("deviation:Q", title="Deviation", format="+.1%"),
        ],
    )
    baseline = base.mark_line(strokeDash=[5, 5], color=ui.PALETTE["navy"]).encode(y="baseline:Q")
    flags = (
        alt.Chart(flagged)
        .mark_point(size=200, filled=True, shape="diamond", stroke="#FFFFFF", strokeWidth=1)
        .encode(
            x="yearmonth(month):T",
            y="value:Q",
            color=alt.Color("impact:N", title=None,
                            scale=alt.Scale(domain=["Favourable", "Unfavourable"],
                                            range=[ui.PALETTE["green"], ui.PALETTE["red"]])),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("deviation:Q", title="Deviation", format="+.1%"), "impact:N"],
        )
    )
    st.altair_chart(alt.layer(band, actual, baseline, flags), width="stretch")
    st.caption(f"Grey band = baseline ± {threshold}%. Diamonds = flagged months "
               "(green favourable, red unfavourable). Dashed line = trailing average.")

with ui.card(f"Flagged months ({len(flagged)})", ":material/flag:"):
    if flagged.empty:
        st.success(f"No month deviates by {threshold}% or more from its trailing {int(window)}-month average.",
                   icon=":material/check_circle:")
    else:
        st.dataframe(
            flagged[["month", "value", "baseline", "deviation", "orders", "impact"]],
            hide_index=True,
            width="stretch",
            column_config={
                "month": st.column_config.DateColumn("Month", format="YYYY-MM"),
                "value": st.column_config.NumberColumn("Actual", format="percent" if is_pct else "%.2f"),
                "baseline": st.column_config.NumberColumn("Baseline", format="percent" if is_pct else "%.2f"),
                "deviation": st.column_config.NumberColumn("Deviation", format="percent"),
                "orders": st.column_config.NumberColumn("Orders", format="%d"),
                "impact": "Impact",
            },
        )

st.caption(
    f"Baseline = mean of the previous {int(window)} eligible months (the first {int(window)} months have no baseline). "
    f"{len(monthly) - len(m)} month(s) excluded for having fewer than {min_orders} orders. "
    "Check the Sales, Delivery and Satisfaction pages for the same months before acting."
)
