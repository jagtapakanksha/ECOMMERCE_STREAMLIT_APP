import altair as alt
import streamlit as st

import data
import ui

start, end, states = data.filters()

with st.spinner("Loading delivery data..."):
    kpi = data.load_kpis(start, end, states).iloc[0]
    monthly = data.load_monthly(start, end, states)
    by_state = data.load_states_summary(start, end, states)

if not kpi["delivered_orders"]:
    st.info("No delivered orders match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("Delivery speed and reliability against the promised date, by month, state and seller.")

late_rate = kpi["late_rate"] or 0
ui.kpi_row([
    dict(label="Delivered orders", value=data.num(kpi["delivered_orders"]), color="blue", icon=":material/inventory:",
         help="Status 'delivered' with both delivered and estimated dates."),
    dict(label="On-time rate", value=data.pct(1 - late_rate, 2), color="green", icon=":material/task_alt:",
         help="Delivered on or before the estimated date."),
    dict(label="Late deliveries", value=data.num(kpi["late_orders"]), color="red", icon=":material/running_with_errors:"),
    dict(label="Late delivery rate", value=data.pct(late_rate, 2), color="red", icon=":material/schedule:",
         chart_data=monthly["late_rate"].fillna(0).tolist(), chart_type="line"),
    dict(label="Avg delivery time", value=f"{data.num(kpi['avg_delivery_days'], 1)} days", color="teal",
         icon=":material/local_shipping:", chart_data=monthly["avg_delivery_days"].fillna(0).tolist(),
         chart_type="line", help="Purchase to customer delivery, delivered orders."),
    dict(label="Avg delay when late", value=f"{data.num(kpi['avg_days_late'], 1)} days", color="orange",
         icon=":material/hourglass_bottom:", help="Days after the estimated date, late orders only."),
])

with ui.card("Late rate and delivery time by month", ":material/timeline:",
             "Bars = late delivery rate (left axis). Line = average delivery days (right axis)."):
    base = alt.Chart(monthly).encode(x=alt.X("yearmonth(month):T", title=None))
    late = base.mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
        y=alt.Y("late_rate:Q", title="Late rate", axis=alt.Axis(format="%")),
        color=alt.Color("late_rate:Q", scale=alt.Scale(range=ui.SCALE_BAD), legend=None),
    )
    days = base.mark_line(point=True, color=ui.PALETTE["navy"], strokeWidth=2.5).encode(
        y=alt.Y("avg_delivery_days:Q", title="Avg delivery days"),
        tooltip=[
            alt.Tooltip("yearmonth(month):T", title="Month"),
            alt.Tooltip("late_rate:Q", title="Late rate", format=".1%"),
            alt.Tooltip("avg_delivery_days:Q", title="Avg delivery days", format=".1f"),
            alt.Tooltip("delivered_orders:Q", title="Delivered", format=","),
        ],
    )
    st.altair_chart(alt.layer(late, days).resolve_scale(y="independent"), width="stretch")

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.markdown("#### :material/map: Delivery performance by customer state")
        min_state_orders = st.selectbox("Min delivered orders", [0, 50, 100, 250, 500, 1000], index=2,
                                        key="delivery_min_state_orders", width=180)
    s = by_state[by_state["delivered_orders"] >= min_state_orders].sort_values("late_rate", ascending=False)
    bars = (
        alt.Chart(s)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("state:N", sort="-y", title=None),
            y=alt.Y("late_rate:Q", title="Late rate", axis=alt.Axis(format="%")),
            color=alt.Color("late_rate:Q", title="Late rate", scale=alt.Scale(range=ui.SCALE_BAD),
                            legend=alt.Legend(format="%")),
            tooltip=[
                "state",
                alt.Tooltip("late_rate:Q", title="Late rate", format=".1%"),
                alt.Tooltip("avg_delivery_days:Q", title="Avg delivery days", format=".1f"),
                alt.Tooltip("delivered_orders:Q", title="Delivered", format=","),
                alt.Tooltip("avg_review_score:Q", title="Avg score", format=".2f"),
            ],
        )
    )
    avg_rule = alt.Chart(s.head(1).assign(overall=late_rate)).mark_rule(
        strokeDash=[5, 4], color=ui.PALETTE["navy"]).encode(y="overall:Q")
    st.altair_chart(alt.layer(bars, avg_rule), width="stretch")
    st.caption(f"Dashed line = overall late rate for the selection ({data.pct(late_rate)}).")

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.markdown("#### :material/storefront: Sellers with the highest late-delivery rates")
        min_seller_orders = st.selectbox("Min delivered orders per seller", [10, 20, 30, 50, 100, 200], index=2,
                                         key="delivery_min_seller_orders", width=220)
    with st.spinner("Loading sellers..."):
        sellers = data.load_sellers(start, end, states, int(min_seller_orders))
    if sellers.empty:
        st.info("No sellers meet the minimum order threshold.", icon=":material/info:")
    else:
        st.dataframe(
            sellers,
            hide_index=True,
            width="stretch",
            column_config={
                "seller_id": "Seller ID",
                "seller_state": "Seller state",
                "delivered_orders": st.column_config.NumberColumn("Delivered orders", format="%d"),
                "late_orders": st.column_config.NumberColumn("Late orders", format="%d"),
                "late_rate": st.column_config.ProgressColumn("Late rate", format="percent", min_value=0, max_value=1,
                                                             color="red"),
                "avg_days_late": st.column_config.NumberColumn("Avg days late", format="%.1f"),
                "avg_delivery_days": st.column_config.NumberColumn("Avg delivery days", format="%.1f"),
                "avg_review_score": st.column_config.NumberColumn("Avg score", format="%.2f"),
            },
        )
    st.caption(
        "Top 25 sellers by late rate. An order with items from several sellers counts for each seller; "
        "lateness is measured at order level, so it cannot be split between sellers or carriers."
    )
