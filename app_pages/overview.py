import altair as alt
import streamlit as st

import data
import ui

start, end, states = data.filters()

with st.spinner("Loading overview..."):
    kpi = data.load_kpis(start, end, states).iloc[0]
    monthly = data.load_monthly(start, end, states)

if not kpi["orders"]:
    st.info("No orders match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("Headline sales, delivery and satisfaction performance for the selected period and states.")

ui.kpi_row([
    dict(label="Product revenue", value=data.brl_short(kpi["product_revenue"]), color="blue",
         icon=":material/payments:", chart_data=monthly["product_revenue"].tolist(),
         help="SUM(PRICE) from order items, excluding freight."),
    dict(label="Orders", value=data.num(kpi["orders"]), color="violet", icon=":material/receipt_long:",
         chart_data=monthly["orders"].tolist(), help="Distinct orders purchased in the selected period."),
    dict(label="Average order value", value=data.brl(kpi["aov"]), color="teal", icon=":material/shopping_cart:",
         chart_data=monthly["aov"].fillna(0).tolist(), chart_type="line",
         help="Product revenue / orders that contain items."),
    dict(label="Freight revenue", value=data.brl_short(kpi["freight_revenue"]), color="orange",
         icon=":material/local_shipping:", chart_data=monthly["freight_revenue"].tolist()),
    dict(label="Late delivery rate", value=data.pct(kpi["late_rate"]), color="red", icon=":material/schedule:",
         chart_data=monthly["late_rate"].fillna(0).tolist(), chart_type="line",
         help="Delivered orders that arrived after the estimated date."),
    dict(label="Avg review score", value=f"{data.num(kpi['avg_review_score'], 2)} / 5", color="green",
         icon=":material/star:", chart_data=monthly["avg_review_score"].fillna(0).tolist(), chart_type="line",
         help="Mean of per-order average review scores (1-5)."),
])

col1, col2 = st.columns([3, 2])
with col1:
    with ui.card("Monthly product revenue", ":material/bar_chart:"):
        base = alt.Chart(monthly).encode(x=alt.X("yearmonth(month):T", title=None))
        area = base.mark_area(
            line={"color": ui.PALETTE["blue"], "strokeWidth": 2},
            color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                               stops=[alt.GradientStop(color="#FFFFFF", offset=0),
                                      alt.GradientStop(color=ui.PALETTE["blue"], offset=1)]),
            opacity=0.55,
        ).encode(
            y=alt.Y("product_revenue:Q", title="Product revenue (BRL)", axis=alt.Axis(format="~s")),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("product_revenue:Q", title="Revenue (BRL)", format=",.2f"),
                     alt.Tooltip("orders:Q", title="Orders", format=",")],
        )
        points = base.mark_circle(size=40, color=ui.PALETTE["navy"]).encode(y="product_revenue:Q")
        st.altair_chart(alt.layer(area, points), width="stretch")

with col2:
    with ui.card("Orders and average order value", ":material/stacked_line_chart:"):
        base = alt.Chart(monthly).encode(x=alt.X("yearmonth(month):T", title=None))
        bars = base.mark_bar(color=ui.PALETTE["violet"], opacity=0.35, cornerRadiusTopLeft=3,
                             cornerRadiusTopRight=3).encode(y=alt.Y("orders:Q", title="Orders"))
        line = base.mark_line(point=True, color=ui.PALETTE["teal"], strokeWidth=2.5).encode(
            y=alt.Y("aov:Q", title="AOV (BRL)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("orders:Q", title="Orders", format=","),
                     alt.Tooltip("aov:Q", title="AOV (BRL)", format=",.2f")],
        )
        st.altair_chart(alt.layer(bars, line).resolve_scale(y="independent"), width="stretch")

col3, col4 = st.columns(2)
with col3:
    with ui.card("Late delivery rate by month", ":material/schedule:"):
        chart = alt.Chart(monthly).mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3).encode(
            x=alt.X("yearmonth(month):T", title=None),
            y=alt.Y("late_rate:Q", title="Late rate", axis=alt.Axis(format="%")),
            color=alt.Color("late_rate:Q", scale=alt.Scale(range=ui.SCALE_BAD), legend=None),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("late_rate:Q", title="Late rate", format=".1%"),
                     alt.Tooltip("delivered_orders:Q", title="Delivered", format=",")],
        )
        st.altair_chart(chart, width="stretch")
with col4:
    with ui.card("Average review score by month", ":material/star:"):
        chart = alt.Chart(monthly).mark_line(point=True, color=ui.PALETTE["green"], strokeWidth=2.5).encode(
            x=alt.X("yearmonth(month):T", title=None),
            y=alt.Y("avg_review_score:Q", title="Avg score (1-5)", scale=alt.Scale(zero=False)),
            tooltip=[alt.Tooltip("yearmonth(month):T", title="Month"),
                     alt.Tooltip("avg_review_score:Q", title="Avg score", format=".2f")],
        )
        st.altair_chart(chart, width="stretch")

with st.expander("Monthly detail table", icon=":material/table_view:"):
    st.dataframe(
        monthly,
        hide_index=True,
        width="stretch",
        column_config={
            "month": st.column_config.DateColumn("Month", format="YYYY-MM"),
            "orders": st.column_config.NumberColumn("Orders", format="%d"),
            "product_revenue": st.column_config.NumberColumn("Product revenue (BRL)", format="%.2f"),
            "freight_revenue": st.column_config.NumberColumn("Freight (BRL)", format="%.2f"),
            "aov": st.column_config.NumberColumn("AOV (BRL)", format="%.2f"),
            "customers": st.column_config.NumberColumn("Customers", format="%d"),
            "delivered_orders": st.column_config.NumberColumn("Delivered", format="%d"),
            "late_rate": st.column_config.NumberColumn("Late rate", format="percent"),
            "avg_delivery_days": st.column_config.NumberColumn("Avg delivery days", format="%.1f"),
            "avg_review_score": st.column_config.NumberColumn("Avg score", format="%.2f"),
        },
    )

st.caption(
    f"{data.num(kpi['orders'])} orders, {data.num(kpi['orders_with_items'])} with items, "
    f"{data.num(kpi['delivered_orders'])} delivered with both dates. "
    "The first and last month may be partial if the range does not start/end on a month boundary."
)
