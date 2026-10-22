import altair as alt
import pandas as pd
import streamlit as st

import data
import ui

start, end, states = data.filters()

with st.spinner("Loading review data..."):
    kpi = data.load_kpis(start, end, states).iloc[0]
    dist = data.load_score_distribution(start, end, states)
    by_delay = data.load_score_by_delay(start, end, states)
    cats = data.load_categories(start, end, states)

if dist.empty:
    st.info("No reviews match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("Customer review scores, how delivery delays affect them, and which big categories are rated poorly.")

SCORE_COLORS = ["#DE350B", "#FF8B00", "#FFAB00", "#7BC8A4", "#36B37E"]

total_reviews = dist["reviews"].sum()
five_star = dist.loc[dist["review_score"] == 5, "reviews"].sum() / total_reviews
low = dist.loc[dist["review_score"] <= 2, "reviews"].sum() / total_reviews
on_time = by_delay.loc[by_delay["sort_key"] == 0]
late = by_delay.loc[by_delay["sort_key"] > 0]
late_score = (late["avg_review_score"] * late["orders"]).sum() / late["orders"].sum() if not late.empty else None

ui.kpi_row([
    dict(label="Avg review score", value=f"{data.num(kpi['avg_review_score'], 2)} / 5", color="green",
         icon=":material/star:", help="Mean of per-order average review scores (1-5)."),
    dict(label="Reviewed orders", value=data.num(kpi["reviewed_orders"]), color="blue", icon=":material/rate_review:"),
    dict(label="5-star share", value=data.pct(five_star), color="teal", icon=":material/thumb_up:"),
    dict(label="1-2 star share", value=data.pct(low), color="red", icon=":material/thumb_down:"),
    dict(label="Score when late", value=data.num(late_score, 2) if late_score is not None else "–", color="orange",
         icon=":material/schedule:", help="Average score of orders delivered after the estimated date."),
])

col1, col2 = st.columns(2)
with col1:
    with ui.card("Review score distribution", ":material/star_half:"):
        d = dist.copy()
        d["share"] = d["reviews"] / total_reviews
        chart = (
            alt.Chart(d)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("review_score:O", title="Score"),
                y=alt.Y("reviews:Q", title="Reviews", axis=alt.Axis(format="~s")),
                color=alt.Color("review_score:O", scale=alt.Scale(domain=[1, 2, 3, 4, 5], range=SCORE_COLORS),
                                legend=None),
                tooltip=[
                    alt.Tooltip("review_score:O", title="Score"),
                    alt.Tooltip("reviews:Q", title="Reviews", format=","),
                    alt.Tooltip("share:Q", title="Share", format=".1%"),
                ],
            )
        )
        labels = chart.mark_text(dy=-8, color="#1B2B3A", fontSize=11).encode(text=alt.Text("share:Q", format=".0%"))
        st.altair_chart(alt.layer(chart, labels), width="stretch")

with col2:
    with ui.card("Score vs delivery delay", ":material/timer:"):
        order = by_delay.sort_values("sort_key")["delivery_bucket"].tolist()
        chart = (
            alt.Chart(by_delay)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("delivery_bucket:N", sort=order, title="Delivered vs estimated date",
                        axis=alt.Axis(labelAngle=0)),
                y=alt.Y("avg_review_score:Q", title="Avg score", scale=alt.Scale(domain=[1, 5])),
                color=alt.Color("avg_review_score:Q", legend=None,
                                scale=alt.Scale(domain=[1.5, 2.5, 3.5, 4.3], range=ui.SCALE_GOOD, clamp=True)),
                tooltip=[
                    alt.Tooltip("delivery_bucket:N", title="Delivery"),
                    alt.Tooltip("orders:Q", title="Orders", format=","),
                    alt.Tooltip("avg_review_score:Q", title="Avg score", format=".2f"),
                    alt.Tooltip("low_score_share:Q", title="1-2 star share", format=".1%"),
                ],
            )
        )
        labels = chart.mark_text(dy=-8, color="#1B2B3A", fontSize=11).encode(
            text=alt.Text("avg_review_score:Q", format=".2f"))
        st.altair_chart(alt.layer(chart, labels), width="stretch")
        if not on_time.empty and late_score is not None:
            st.caption(
                f"On-time orders average {on_time['avg_review_score'].iloc[0]:.2f}; "
                f"late orders average {late_score:.2f}. This is an association, not proof of cause."
            )

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.markdown("#### :material/report: High-revenue categories with low ratings")
        min_reviews = st.selectbox("Min reviewed orders", [25, 50, 100, 250, 500, 1000], index=2,
                                   key="sat_min_reviews", width=170)
        max_score = st.selectbox("Score below", [3.5, 3.8, 4.0, 4.1, 4.2], index=2, key="sat_max_score", width=130)
    c = cats[cats["reviewed_orders"] >= min_reviews].copy()
    if c.empty:
        st.info("No categories meet the minimum review threshold.", icon=":material/info:")
    else:
        median_rev = c["revenue"].median()
        c["flag"] = (c["revenue"] >= median_rev) & (c["avg_review_score"] < max_score)
        c["status"] = c["flag"].map({True: "At risk", False: "Other"})
        scatter = (
            alt.Chart(c)
            .mark_circle(opacity=0.8, stroke="#FFFFFF", strokeWidth=0.5)
            .encode(
                x=alt.X("revenue:Q", title="Product revenue (BRL)", scale=alt.Scale(type="log")),
                y=alt.Y("avg_review_score:Q", title="Avg score", scale=alt.Scale(zero=False)),
                size=alt.Size("reviewed_orders:Q", legend=None, scale=alt.Scale(range=[30, 700])),
                color=alt.Color("status:N", title=None,
                                scale=alt.Scale(domain=["At risk", "Other"], range=[ui.PALETTE["red"], ui.PALETTE["grey"]])),
                tooltip=[
                    "category",
                    alt.Tooltip("revenue:Q", title="Revenue (BRL)", format=",.0f"),
                    alt.Tooltip("avg_review_score:Q", title="Avg score", format=".2f"),
                    alt.Tooltip("reviewed_orders:Q", title="Reviewed orders", format=","),
                ],
            )
        )
        rule = alt.Chart(pd.DataFrame({"threshold": [max_score]})).mark_rule(
            strokeDash=[4, 4], color=ui.PALETTE["red"]).encode(y="threshold:Q")
        st.altair_chart(alt.layer(scatter, rule), width="stretch")
        flagged = c[c["flag"]].sort_values("revenue", ascending=False)
        st.markdown(f":red-badge[:material/warning: {len(flagged)} at-risk categories]")
        st.dataframe(
            flagged[["category", "revenue", "orders", "avg_review_score", "reviewed_orders", "avg_price", "freight_to_price"]],
            hide_index=True,
            width="stretch",
            column_config={
                "category": "Category",
                "revenue": st.column_config.NumberColumn("Revenue (BRL)", format="%.2f"),
                "orders": st.column_config.NumberColumn("Orders", format="%d"),
                "avg_review_score": st.column_config.NumberColumn("Avg score", format="%.2f"),
                "reviewed_orders": st.column_config.NumberColumn("Reviewed orders", format="%d"),
                "avg_price": st.column_config.NumberColumn("Avg item price (BRL)", format="%.2f"),
                "freight_to_price": st.column_config.NumberColumn("Freight / price", format="percent"),
            },
        )
        st.caption(
            f"At risk = revenue at or above the median of eligible categories ({data.brl(median_rev, 0)}) "
            f"and average score below {max_score:.1f}."
        )

st.caption(
    "Scores are averaged per order first (some orders have several reviews). "
    "Category scores use every order that contains the category."
)
