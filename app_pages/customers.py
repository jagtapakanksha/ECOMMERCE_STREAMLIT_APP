import altair as alt
import streamlit as st

import data
import ui

start, end, states = data.filters()

with st.spinner("Loading customer data..."):
    freq = data.load_customer_frequency(start, end, states)
    deciles = data.load_customer_deciles(start, end, states)
    by_state = data.load_states_summary(start, end, states)

if freq.empty:
    st.info("No orders match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("How many customers buy, how often they come back, and how concentrated spending is.")

total_customers = freq["customers"].sum()
repeat = freq[freq["orders_bucket"] != "1"]
repeat_customers = repeat["customers"].sum()
repeat_rate = repeat_customers / total_customers if total_customers else None
repeat_rev_share = repeat["revenue"].sum() / freq["revenue"].sum() if freq["revenue"].sum() else None
orders_per_customer = freq["orders"].sum() / total_customers if total_customers else None
top_decile_share = (
    deciles.loc[deciles["decile"] == 1, "revenue"].sum() / deciles["revenue"].sum() if not deciles.empty else None
)

ui.kpi_row([
    dict(label="Unique customers", value=data.num(total_customers), color="blue", icon=":material/group:",
         help="Distinct CUSTOMER_UNIQUE_ID with at least one order in the period."),
    dict(label="Repeat customers", value=data.num(repeat_customers), color="violet", icon=":material/autorenew:",
         help="Customers with 2+ orders in the selected period."),
    dict(label="Repeat purchase rate", value=data.pct(repeat_rate, 2), color="teal", icon=":material/percent:"),
    dict(label="Revenue from repeat", value=data.pct(repeat_rev_share), color="green", icon=":material/savings:"),
    dict(label="Orders per customer", value=data.num(orders_per_customer, 3), color="orange",
         icon=":material/shopping_bag:"),
    dict(label="Top 10% revenue share", value=data.pct(top_decile_share), color="navy",
         icon=":material/workspace_premium:", help="Share of product revenue from the top-spending 10% of customers."),
])

f = freq.copy()
f["share"] = f["customers"] / total_customers
d = deciles.copy()
d["revenue_share"] = d["revenue"] / d["revenue"].sum()
d["segment"] = d["decile"].map(lambda x: "Top 10%" if x == 1 else "Other deciles")

col1, col2 = st.columns(2)
with col1:
    with ui.card("Orders per customer", ":material/shopping_bag:", "Y axis is symlog so the small repeat groups stay visible."):
        chart = (
            alt.Chart(f)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("orders_bucket:N", title="Orders in period", sort=["1", "2", "3", "4+"]),
                y=alt.Y("customers:Q", title="Customers", scale=alt.Scale(type="symlog")),
                color=alt.Color("orders_bucket:N", legend=None, sort=["1", "2", "3", "4+"],
                                scale=alt.Scale(range=[ui.PALETTE["grey"], ui.PALETTE["teal"], ui.PALETTE["blue"],
                                                       ui.PALETTE["violet"]])),
                tooltip=[
                    alt.Tooltip("orders_bucket:N", title="Orders"),
                    alt.Tooltip("customers:Q", title="Customers", format=","),
                    alt.Tooltip("share:Q", title="Share", format=".2%"),
                    alt.Tooltip("revenue:Q", title="Revenue (BRL)", format=",.2f"),
                ],
            )
        )
        st.altair_chart(chart, width="stretch")

with col2:
    with ui.card("Revenue concentration by customer decile", ":material/stacked_bar_chart:",
                 "Decile 1 = the highest-spending 10% of customers."):
        chart = (
            alt.Chart(d)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("decile:O", title="Customer decile"),
                y=alt.Y("revenue_share:Q", title="Share of product revenue", axis=alt.Axis(format="%")),
                color=alt.Color("segment:N", legend=None,
                                scale=alt.Scale(domain=["Top 10%", "Other deciles"],
                                                range=[ui.PALETTE["navy"], ui.PALETTE["blue"]])),
                tooltip=[
                    alt.Tooltip("decile:O", title="Decile"),
                    alt.Tooltip("customers:Q", title="Customers", format=","),
                    alt.Tooltip("revenue_share:Q", title="Revenue share", format=".1%"),
                    alt.Tooltip("avg_revenue:Q", title="Avg spend (BRL)", format=",.2f"),
                    alt.Tooltip("avg_orders:Q", title="Avg orders", format=".2f"),
                ],
            )
        )
        st.altair_chart(chart, width="stretch")

with ui.card("High-value customer segments", ":material/workspace_premium:",
             "Aggregated segments only; individual customer identifiers are not shown."):
    st.dataframe(
        d[["decile", "customers", "revenue", "revenue_share", "avg_revenue", "min_revenue", "avg_orders"]],
        hide_index=True,
        width="stretch",
        column_config={
            "decile": st.column_config.NumberColumn("Decile", format="%d"),
            "customers": st.column_config.NumberColumn("Customers", format="%d"),
            "revenue": st.column_config.NumberColumn("Revenue (BRL)", format="%.2f"),
            "revenue_share": st.column_config.ProgressColumn("Revenue share", format="percent", min_value=0,
                                                             max_value=float(max(d["revenue_share"].max(), 0.01))),
            "avg_revenue": st.column_config.NumberColumn("Avg spend (BRL)", format="%.2f"),
            "min_revenue": st.column_config.NumberColumn("Min spend in decile (BRL)", format="%.2f"),
            "avg_orders": st.column_config.NumberColumn("Avg orders", format="%.2f"),
        },
    )

with ui.card("Customers by state", ":material/map:"):
    s = by_state.sort_values("customers", ascending=False).copy()
    s["orders_per_customer"] = s["orders"] / s["customers"]
    chart = (
        alt.Chart(s)
        .mark_bar(color=ui.PALETTE["teal"], cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("state:N", sort="-y", title=None),
            y=alt.Y("customers:Q", title="Customers", axis=alt.Axis(format="~s")),
            tooltip=[
                "state",
                alt.Tooltip("customers:Q", title="Customers", format=","),
                alt.Tooltip("orders_per_customer:Q", title="Orders / customer", format=".3f"),
                alt.Tooltip("aov:Q", title="AOV (BRL)", format=",.2f"),
            ],
        )
    )
    st.altair_chart(chart, width="stretch")

st.caption(
    "Customers are identified by CUSTOMER_UNIQUE_ID (CUSTOMER_ID is issued per order). "
    "Repeat behaviour is measured only inside the selected date range, so short ranges understate it."
)
