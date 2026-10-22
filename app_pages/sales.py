import altair as alt
import streamlit as st

import data
import ui

start, end, states = data.filters()

with st.spinner("Loading sales data..."):
    cats = data.load_categories(start, end, states)
    by_state = data.load_states_summary(start, end, states)
    payments = data.load_payments(start, end, states)
    installments = data.load_installments(start, end, states)

if cats.empty:
    st.info("No orders match the current filters.", icon=":material/filter_alt_off:")
    st.stop()

ui.page_intro("Where product revenue comes from: categories, states and how customers pay.")

total_rev = cats["revenue"].sum()
top_cat = cats.iloc[0]
state_sorted = by_state.sort_values("revenue", ascending=False)
top_state = state_sorted.iloc[0]
pay = payments.copy()
pay["share"] = pay["payment_value"] / pay["payment_value"].sum()
card_share = pay.loc[pay["payment_type"] == "credit_card", "share"].sum()

ui.kpi_row([
    dict(label="Product revenue", value=data.brl_short(total_rev), color="blue", icon=":material/payments:"),
    dict(label="Top category", value=top_cat["category"], color="violet", icon=":material/category:",
         help=f"{data.brl_short(top_cat['revenue'])} · {data.pct(top_cat['revenue'] / total_rev)} of product revenue"),
    dict(label="Top state", value=f"{top_state['state']} · {data.pct(top_state['revenue'] / by_state['revenue'].sum())}",
         color="teal", icon=":material/location_on:", help="Share of product revenue from the top customer state."),
    dict(label="Credit card share", value=data.pct(card_share), color="orange", icon=":material/credit_card:",
         help="Share of payment value paid by credit card."),
    dict(label="Categories sold", value=data.num(len(cats)), color="navy", icon=":material/inventory_2:"),
])

# ----------------------------------------------------------------- categories
RANK_BY = {"Revenue": "revenue", "Orders": "orders"}

with st.container(border=True):
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.markdown("#### :material/leaderboard: Top product categories")
        rank_label = st.segmented_control("Rank by", list(RANK_BY), default="Revenue", key="sales_rank_by",
                                          width="content")
        top_n = st.selectbox("Show", [5, 10, 15, 20, 30], index=1, key="sales_top_n", width=110,
                             format_func=lambda n: f"Top {n}")
    rank_col = RANK_BY[rank_label or "Revenue"]

    top = cats.sort_values(rank_col, ascending=False).head(int(top_n)).copy()
    top["revenue_share"] = top["revenue"] / total_rev

    chart = (
        alt.Chart(top)
        .mark_bar(cornerRadiusTopRight=4, cornerRadiusBottomRight=4)
        .encode(
            x=alt.X(f"{rank_col}:Q", title=rank_label, axis=alt.Axis(format="~s")),
            y=alt.Y("category:N", sort="-x", title=None),
            color=alt.Color("avg_review_score:Q", title="Avg score",
                            scale=alt.Scale(domain=[3.6, 3.9, 4.1, 4.4], range=ui.SCALE_GOOD, clamp=True)),
            tooltip=[
                "category",
                alt.Tooltip("revenue:Q", title="Revenue (BRL)", format=",.2f"),
                alt.Tooltip("orders:Q", title="Orders", format=","),
                alt.Tooltip("avg_price:Q", title="Avg item price", format=",.2f"),
                alt.Tooltip("avg_review_score:Q", title="Avg score", format=".2f"),
            ],
        )
    )
    st.altair_chart(chart, width="stretch")
    st.dataframe(
        top[["category", "revenue", "revenue_share", "orders", "items", "avg_price", "avg_freight", "freight_to_price", "avg_review_score"]],
        hide_index=True,
        width="stretch",
        column_config={
            "category": "Category",
            "revenue": st.column_config.NumberColumn("Revenue (BRL)", format="%.2f"),
            "revenue_share": st.column_config.ProgressColumn("Share of revenue", format="percent", min_value=0,
                                                             max_value=float(max(top["revenue_share"].max(), 0.01))),
            "orders": st.column_config.NumberColumn("Orders", format="%d"),
            "items": st.column_config.NumberColumn("Items", format="%d"),
            "avg_price": st.column_config.NumberColumn("Avg item price (BRL)", format="%.2f"),
            "avg_freight": st.column_config.NumberColumn("Avg freight (BRL)", format="%.2f"),
            "freight_to_price": st.column_config.NumberColumn("Freight / price", format="percent"),
            "avg_review_score": st.column_config.NumberColumn("Avg score", format="%.2f"),
        },
    )
    st.caption(
        f"Top {int(top_n)} categories = {data.pct(top['revenue'].sum() / total_rev)} of product revenue. "
        "Bar color = average review score. Orders with several categories count once in each. "
        "Category names are the original Portuguese values."
    )

col_a, col_b = st.columns(2)
# ----------------------------------------------------------------- price vs freight
with col_a:
    with ui.card("Item price vs freight by category", ":material/scatter_plot:",
                 "Categories with at least 100 items. Bubble size = product revenue. Price axis is log scale."):
        scatter_src = cats[cats["items"] >= 100]
        scatter = (
            alt.Chart(scatter_src)
            .mark_circle(opacity=0.75, color=ui.PALETTE["violet"], stroke="#FFFFFF", strokeWidth=0.5)
            .encode(
                x=alt.X("avg_price:Q", title="Avg item price (BRL)", scale=alt.Scale(type="log")),
                y=alt.Y("freight_to_price:Q", title="Freight as % of price", axis=alt.Axis(format="%")),
                size=alt.Size("revenue:Q", title="Revenue", legend=None, scale=alt.Scale(range=[30, 900])),
                tooltip=[
                    "category",
                    alt.Tooltip("avg_price:Q", title="Avg price", format=",.2f"),
                    alt.Tooltip("avg_freight:Q", title="Avg freight", format=",.2f"),
                    alt.Tooltip("freight_to_price:Q", title="Freight / price", format=".1%"),
                    alt.Tooltip("revenue:Q", title="Revenue (BRL)", format=",.0f"),
                ],
            )
        )
        st.altair_chart(scatter, width="stretch")

# ----------------------------------------------------------------- states
with col_b:
    with ui.card("Sales by customer state", ":material/map:"):
        state_chart = (
            alt.Chart(state_sorted)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("state:N", sort="-y", title=None),
                y=alt.Y("revenue:Q", title="Product revenue (BRL)", axis=alt.Axis(format="~s")),
                color=alt.condition(alt.datum.state == top_state["state"], alt.value(ui.PALETTE["navy"]),
                                    alt.value(ui.PALETTE["blue"])),
                tooltip=[
                    "state",
                    alt.Tooltip("revenue:Q", title="Revenue (BRL)", format=",.2f"),
                    alt.Tooltip("orders:Q", title="Orders", format=","),
                    alt.Tooltip("aov:Q", title="AOV (BRL)", format=",.2f"),
                ],
            )
        )
        st.altair_chart(state_chart, width="stretch")

with st.expander("State detail table", icon=":material/table_view:"):
    s = state_sorted.copy()
    s["revenue_share"] = s["revenue"] / s["revenue"].sum()
    st.dataframe(
        s[["state", "revenue", "revenue_share", "orders", "aov", "customers"]],
        hide_index=True,
        width="stretch",
        column_config={
            "state": "State",
            "revenue": st.column_config.NumberColumn("Revenue (BRL)", format="%.2f"),
            "revenue_share": st.column_config.ProgressColumn("Share", format="percent", min_value=0,
                                                             max_value=float(max(s["revenue_share"].max(), 0.01))),
            "orders": st.column_config.NumberColumn("Orders", format="%d"),
            "aov": st.column_config.NumberColumn("AOV (BRL)", format="%.2f"),
            "customers": st.column_config.NumberColumn("Customers", format="%d"),
        },
    )

# ----------------------------------------------------------------- payments
col1, col2 = st.columns(2)
with col1:
    with ui.card("Payment value by method", ":material/account_balance_wallet:"):
        pay_chart = (
            alt.Chart(pay)
            .mark_arc(innerRadius=60, outerRadius=110, stroke="#FFFFFF", strokeWidth=2)
            .encode(
                theta=alt.Theta("payment_value:Q"),
                color=alt.Color("payment_type:N", title="Method", scale=alt.Scale(range=ui.SERIES)),
                tooltip=[
                    alt.Tooltip("payment_type:N", title="Method"),
                    alt.Tooltip("payment_value:Q", title="Value (BRL)", format=",.2f"),
                    alt.Tooltip("share:Q", title="Share", format=".1%"),
                    alt.Tooltip("orders:Q", title="Orders", format=","),
                ],
            )
        )
        st.altair_chart(pay_chart, width="stretch")
        st.dataframe(
            pay[["payment_type", "payment_value", "share", "orders", "payments", "avg_installments"]],
            hide_index=True,
            width="stretch",
            column_config={
                "payment_type": "Method",
                "payment_value": st.column_config.NumberColumn("Value (BRL)", format="%.2f"),
                "share": st.column_config.ProgressColumn("Share", format="percent", min_value=0, max_value=1),
                "orders": st.column_config.NumberColumn("Orders", format="%d"),
                "payments": st.column_config.NumberColumn("Payments", format="%d"),
                "avg_installments": st.column_config.NumberColumn("Avg installments", format="%.2f"),
            },
        )

with col2:
    with ui.card("Credit card installments", ":material/credit_score:"):
        inst_chart = (
            alt.Chart(installments)
            .mark_bar(color=ui.PALETTE["orange"], cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("installments:O", title="Installments"),
                y=alt.Y("payments:Q", title="Payments"),
                tooltip=[
                    alt.Tooltip("installments:O", title="Installments"),
                    alt.Tooltip("payments:Q", title="Payments", format=","),
                    alt.Tooltip("avg_payment_value:Q", title="Avg payment (BRL)", format=",.2f"),
                ],
            )
        )
        st.altair_chart(inst_chart, width="stretch")
        if not installments.empty:
            single = installments.loc[installments["installments"] == 1, "payments"].sum() / installments["payments"].sum()
            st.caption(f"{data.pct(single)} of credit card payments are a single installment.")

st.caption("Payment value includes freight and vouchers, so it does not equal product revenue.")
