"""Shared data access for the E-Commerce Intelligence app.

All queries read the typed views in ECOMMERCE_DB.STAGING. Filter values are
passed as qmark bind parameters; the only dynamic SQL text is the number of
"?" placeholders for the state filter.

Metric definitions
- Product revenue = SUM(PRICE) from STG_ORDER_ITEMS (excludes freight).
- Freight revenue = SUM(FREIGHT_VALUE) from STG_ORDER_ITEMS.
- AOV = product revenue / number of orders that contain items.
- Late = delivered to customer after the estimated delivery date; rates use
  orders with status 'delivered' and both dates present.
- Items and reviews are aggregated per order before joining to avoid fan-out.
"""

import os
from datetime import date

import pandas as pd
import streamlit as st

# Source schema, default date range (core period without the sparse 2016 and Sep-Oct 2018 months) and how long
# query results stay cached.
STG = "ECOMMERCE_DB.STAGING"
DEFAULT_START = date(2017, 1, 1)
DEFAULT_END = date(2018, 8, 31)
CACHE_TTL = "30m"
# Label/ID columns that must stay text even if every value looks numeric.
TEXT_COLUMNS = {"orders_bucket", "category", "state", "seller_id", "seller_state", "payment_type", "delivery_bucket"}


def get_conn():
    """Return the app's Snowflake connection (st.connection reuses one connection per process)."""
    return st.connection("snowflake", ttl=os.getenv("SNOWFLAKE_CONNECTION_TTL"))


def _with_filters(body: str, start: date, end: date, states: tuple, extra_params=()) -> tuple:
    """Prefix a query with the filtered-orders CTE and the per-order aggregates."""
    # Only the number of '?' placeholders is generated here; the state codes themselves are bound parameters.
    state_clause = ""
    if states:
        state_clause = f" AND c.customer_state IN ({', '.join(['?'] * len(states))})"
    sql = f"""
WITH f_orders AS (
    SELECT o.order_id, o.order_status, o.order_purchase_month, o.is_delivered, o.is_late,
           o.delivery_days, o.delay_vs_estimate_days, c.customer_unique_id, c.customer_state
    FROM {STG}.STG_ORDERS o
    JOIN {STG}.STG_CUSTOMERS c ON c.customer_id = o.customer_id
    WHERE o.order_purchase_date BETWEEN ? AND ?{state_clause}
),
items_o AS (
    SELECT order_id, SUM(price) AS product_revenue, SUM(freight_value) AS freight, COUNT(*) AS items
    FROM {STG}.STG_ORDER_ITEMS
    WHERE order_id IN (SELECT order_id FROM f_orders)
    GROUP BY order_id
),
reviews_o AS (
    SELECT order_id, AVG(review_score) AS review_score
    FROM {STG}.STG_ORDER_REVIEWS
    WHERE order_id IN (SELECT order_id FROM f_orders)
    GROUP BY order_id
)
{body}
"""
    # Parameter order must match the '?' order in the SQL: dates, then states, then any extras used by the
    # body.
    params = [start, end, *states, *extra_params]
    return sql, params


def _run(sql: str, params: list) -> pd.DataFrame:
    """Run a query through conn.query (cached for CACHE_TTL) and tidy the result. Columns are lowercased;
    NUMBER columns arrive as Decimal objects, so object columns are converted to numbers unless they are
    listed in TEXT_COLUMNS, and 'month' is converted to datetime for the charts.
    """
    df = get_conn().query(sql, params=params, ttl=CACHE_TTL, show_spinner=False)
    df.columns = [c.lower() for c in df.columns]
    for col in df.columns:
        if col == "month":
            df[col] = pd.to_datetime(df[col])
        elif col in TEXT_COLUMNS:
            df[col] = df[col].astype(str)
        elif df[col].dtype == object:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass
    return df


def clear_cache():
    """Drop all st.cache_data entries, including conn.query results (used by the Refresh button)."""
    st.cache_data.clear()


# --------------------------------------------------------------------------- loaders

def load_date_bounds() -> pd.DataFrame:
    """Earliest and latest purchase date in STG_ORDERS (one row: min_date, max_date)."""
    return _run(
        f"SELECT MIN(order_purchase_date) AS min_date, MAX(order_purchase_date) AS max_date FROM {STG}.STG_ORDERS",
        [],
    )


def load_states() -> list:
    """Distinct customer state codes for the state filters."""
    df = _run(f"SELECT DISTINCT customer_state AS state FROM {STG}.STG_CUSTOMERS ORDER BY 1", [])
    return df["state"].tolist()


def load_category_options() -> list:
    """Distinct product categories (including 'unknown') for the agent page dropdown."""
    df = _run(f"SELECT DISTINCT product_category AS category FROM {STG}.STG_PRODUCTS ORDER BY 1", [])
    return df["category"].tolist()


# Named purchase-date ranges shared by the sidebar and the agent page. None = full data range.
PERIODS = {
    "Core period": (date(2017, 1, 1), date(2018, 8, 31)),
    "2017": (date(2017, 1, 1), date(2017, 12, 31)),
    "2018 (Jan–Aug)": (date(2018, 1, 1), date(2018, 8, 31)),
    "All data": None,
}


def load_kpis(start, end, states) -> pd.DataFrame:
    """Headline metrics for the filtered orders (one row). Product revenue and freight come from order items,
    AOV = product revenue / orders with items, the late rate uses delivered orders with both dates, and the
    review score is the mean of per-order averages.
    """
    body = """
SELECT
    COUNT(*)                                                     AS orders,
    COUNT(i.order_id)                                            AS orders_with_items,
    SUM(i.product_revenue)                                       AS product_revenue,
    SUM(i.freight)                                               AS freight_revenue,
    DIV0NULL(SUM(i.product_revenue), COUNT(i.order_id))          AS aov,
    COUNT(DISTINCT f.customer_unique_id)                         AS customers,
    COUNT_IF(f.is_delivered AND f.is_late IS NOT NULL)           AS delivered_orders,
    COUNT_IF(f.is_delivered AND f.is_late)                       AS late_orders,
    DIV0NULL(late_orders, delivered_orders)                      AS late_rate,
    AVG(IFF(f.is_delivered, f.delivery_days, NULL))              AS avg_delivery_days,
    AVG(IFF(f.is_delivered AND f.is_late, f.delay_vs_estimate_days, NULL)) AS avg_days_late,
    AVG(r.review_score)                                          AS avg_review_score,
    COUNT(r.order_id)                                            AS reviewed_orders
FROM f_orders f
LEFT JOIN items_o i ON i.order_id = f.order_id
LEFT JOIN reviews_o r ON r.order_id = f.order_id
"""
    return _run(*_with_filters(body, start, end, states))


def load_monthly(start, end, states) -> pd.DataFrame:
    """The load_kpis metrics plus customers and delivery days, one row per purchase month."""
    body = """
SELECT
    f.order_purchase_month                                       AS month,
    COUNT(*)                                                     AS orders,
    COALESCE(SUM(i.product_revenue), 0)                          AS product_revenue,
    COALESCE(SUM(i.freight), 0)                                  AS freight_revenue,
    DIV0NULL(SUM(i.product_revenue), COUNT(i.order_id))          AS aov,
    COUNT(DISTINCT f.customer_unique_id)                         AS customers,
    COUNT_IF(f.is_delivered AND f.is_late IS NOT NULL)           AS delivered_orders,
    DIV0NULL(COUNT_IF(f.is_delivered AND f.is_late), delivered_orders) AS late_rate,
    AVG(IFF(f.is_delivered, f.delivery_days, NULL))              AS avg_delivery_days,
    AVG(r.review_score)                                          AS avg_review_score
FROM f_orders f
LEFT JOIN items_o i ON i.order_id = f.order_id
LEFT JOIN reviews_o r ON r.order_id = f.order_id
GROUP BY 1
ORDER BY 1
"""
    return _run(*_with_filters(body, start, end, states))


def load_categories(start, end, states) -> pd.DataFrame:
    """One row per product category: revenue, orders, items, price, freight and review score. An order with
    several categories counts once in each.
    """
    body = f"""
, cat_o AS (
    SELECT i.order_id, COALESCE(p.product_category, 'unknown') AS category,
           SUM(i.price) AS revenue, SUM(i.freight_value) AS freight, COUNT(*) AS items
    FROM {STG}.STG_ORDER_ITEMS i
    JOIN f_orders f ON f.order_id = i.order_id
    LEFT JOIN {STG}.STG_PRODUCTS p ON p.product_id = i.product_id
    GROUP BY 1, 2
)
SELECT
    c.category,
    SUM(c.revenue)                                               AS revenue,
    COUNT(DISTINCT c.order_id)                                   AS orders,
    SUM(c.items)                                                 AS items,
    DIV0NULL(SUM(c.revenue), SUM(c.items))                       AS avg_price,
    DIV0NULL(SUM(c.freight), SUM(c.items))                       AS avg_freight,
    DIV0NULL(SUM(c.freight), SUM(c.revenue))                     AS freight_to_price,
    AVG(r.review_score)                                          AS avg_review_score,
    COUNT(r.order_id)                                            AS reviewed_orders
FROM cat_o c
LEFT JOIN reviews_o r ON r.order_id = c.order_id
GROUP BY 1
ORDER BY revenue DESC
"""
    # The body starts with an extra CTE, so it is appended to the WITH list.
    return _run(*_with_filters(body, start, end, states))


def load_states_summary(start, end, states) -> pd.DataFrame:
    """One row per customer state: revenue, orders, AOV, customers, late rate, delivery days and review score."""
    body = """
SELECT
    f.customer_state                                             AS state,
    COUNT(*)                                                     AS orders,
    COALESCE(SUM(i.product_revenue), 0)                          AS revenue,
    DIV0NULL(SUM(i.product_revenue), COUNT(i.order_id))          AS aov,
    COUNT(DISTINCT f.customer_unique_id)                         AS customers,
    COUNT_IF(f.is_delivered AND f.is_late IS NOT NULL)           AS delivered_orders,
    DIV0NULL(COUNT_IF(f.is_delivered AND f.is_late), delivered_orders) AS late_rate,
    AVG(IFF(f.is_delivered, f.delivery_days, NULL))              AS avg_delivery_days,
    AVG(r.review_score)                                          AS avg_review_score
FROM f_orders f
LEFT JOIN items_o i ON i.order_id = f.order_id
LEFT JOIN reviews_o r ON r.order_id = f.order_id
GROUP BY 1
ORDER BY revenue DESC
"""
    return _run(*_with_filters(body, start, end, states))


def load_payments(start, end, states) -> pd.DataFrame:
    """One row per payment method. Payment value includes freight and vouchers, so it differs from product
    revenue.
    """
    body = f"""
SELECT
    p.payment_type,
    COUNT(DISTINCT p.order_id)                                   AS orders,
    COUNT(*)                                                     AS payments,
    SUM(p.payment_value)                                         AS payment_value,
    AVG(p.payment_installments)                                  AS avg_installments
FROM {STG}.STG_ORDER_PAYMENTS p
JOIN f_orders f ON f.order_id = p.order_id
GROUP BY 1
ORDER BY payment_value DESC
"""
    return _run(*_with_filters(body, start, end, states))


def load_installments(start, end, states) -> pd.DataFrame:
    """Credit card payments grouped by number of installments (1 or more)."""
    body = f"""
SELECT
    p.payment_installments                                       AS installments,
    COUNT(*)                                                     AS payments,
    SUM(p.payment_value)                                         AS payment_value,
    AVG(p.payment_value)                                         AS avg_payment_value
FROM {STG}.STG_ORDER_PAYMENTS p
JOIN f_orders f ON f.order_id = p.order_id
WHERE p.payment_type = 'credit_card' AND p.payment_installments >= 1
GROUP BY 1
ORDER BY 1
"""
    return _run(*_with_filters(body, start, end, states))


def load_customer_frequency(start, end, states) -> pd.DataFrame:
    """Customers (CUSTOMER_UNIQUE_ID) bucketed by orders placed in the period: '1', '2', '3', '4+'."""
    body = """
, cust AS (
    SELECT f.customer_unique_id, COUNT(*) AS orders, COALESCE(SUM(i.product_revenue), 0) AS revenue
    FROM f_orders f
    LEFT JOIN items_o i ON i.order_id = f.order_id
    GROUP BY 1
)
SELECT
    IFF(orders >= 4, '4+', orders::VARCHAR)                      AS orders_bucket,
    COUNT(*)                                                     AS customers,
    SUM(orders)                                                  AS orders,
    SUM(revenue)                                                 AS revenue
FROM cust
GROUP BY 1
ORDER BY 1
"""
    return _run(*_with_filters(body, start, end, states))


def load_customer_deciles(start, end, states) -> pd.DataFrame:
    """Customers ranked into 10 equal groups by product revenue (decile 1 = top spenders). Aggregates only; no
    customer identifiers are returned.
    """
    body = """
, cust AS (
    SELECT f.customer_unique_id, COUNT(*) AS orders, COALESCE(SUM(i.product_revenue), 0) AS revenue
    FROM f_orders f
    LEFT JOIN items_o i ON i.order_id = f.order_id
    GROUP BY 1
), ranked AS (
    SELECT *, NTILE(10) OVER (ORDER BY revenue DESC) AS decile FROM cust
)
SELECT
    decile,
    COUNT(*)                                                     AS customers,
    SUM(revenue)                                                 AS revenue,
    AVG(revenue)                                                 AS avg_revenue,
    AVG(orders)                                                  AS avg_orders,
    MIN(revenue)                                                 AS min_revenue
FROM ranked
GROUP BY 1
ORDER BY 1
"""
    return _run(*_with_filters(body, start, end, states))


def load_sellers(start, end, states, min_orders: int) -> pd.DataFrame:
    """Top 25 sellers by late-delivery rate with at least min_orders delivered orders. Lateness is measured
    per order, so an order with items from several sellers counts for each of them.
    """
    body = f"""
, seller_o AS (
    SELECT DISTINCT i.seller_id, i.order_id
    FROM {STG}.STG_ORDER_ITEMS i
    JOIN f_orders f ON f.order_id = i.order_id
)
SELECT
    s.seller_id,
    sl.seller_state,
    COUNT_IF(f.is_delivered AND f.is_late IS NOT NULL)           AS delivered_orders,
    COUNT_IF(f.is_delivered AND f.is_late)                       AS late_orders,
    DIV0NULL(late_orders, delivered_orders)                      AS late_rate,
    AVG(IFF(f.is_delivered AND f.is_late, f.delay_vs_estimate_days, NULL)) AS avg_days_late,
    AVG(IFF(f.is_delivered, f.delivery_days, NULL))              AS avg_delivery_days,
    AVG(r.review_score)                                          AS avg_review_score
FROM seller_o s
JOIN f_orders f ON f.order_id = s.order_id
LEFT JOIN {STG}.STG_SELLERS sl ON sl.seller_id = s.seller_id
LEFT JOIN reviews_o r ON r.order_id = s.order_id
GROUP BY 1, 2
HAVING delivered_orders >= ?
ORDER BY late_rate DESC, delivered_orders DESC
LIMIT 25
"""
    return _run(*_with_filters(body, start, end, states, extra_params=(int(min_orders),)))


def load_score_distribution(start, end, states) -> pd.DataFrame:
    """Number of reviews per score (1-5), counted per review rather than per order."""
    body = f"""
SELECT r.review_score, COUNT(*) AS reviews
FROM {STG}.STG_ORDER_REVIEWS r
JOIN f_orders f ON f.order_id = r.order_id
WHERE r.review_score IS NOT NULL
GROUP BY 1
ORDER BY 1
"""
    return _run(*_with_filters(body, start, end, states))


def load_score_by_delay(start, end, states) -> pd.DataFrame:
    """Average review score of delivered orders, bucketed by how many days they arrived after the estimate.
    sort_key keeps the buckets in logical order.
    """
    body = """
SELECT
    CASE WHEN f.delay_vs_estimate_days <= 0  THEN 'On time / early'
         WHEN f.delay_vs_estimate_days <= 3  THEN '1-3 days late'
         WHEN f.delay_vs_estimate_days <= 7  THEN '4-7 days late'
         WHEN f.delay_vs_estimate_days <= 14 THEN '8-14 days late'
         ELSE '15+ days late' END                                AS delivery_bucket,
    MIN(CASE WHEN f.delay_vs_estimate_days <= 0  THEN 0
             WHEN f.delay_vs_estimate_days <= 3  THEN 1
             WHEN f.delay_vs_estimate_days <= 7  THEN 2
             WHEN f.delay_vs_estimate_days <= 14 THEN 3
             ELSE 4 END)                                         AS sort_key,
    COUNT(*)                                                     AS orders,
    AVG(r.review_score)                                          AS avg_review_score,
    DIV0NULL(COUNT_IF(r.review_score <= 2), COUNT(*))            AS low_score_share
FROM f_orders f
JOIN reviews_o r ON r.order_id = f.order_id
WHERE f.is_delivered AND f.is_late IS NOT NULL
GROUP BY 1
ORDER BY sort_key
"""
    return _run(*_with_filters(body, start, end, states))


# --------------------------------------------------------------------------- formatting

def brl(value, decimals: int = 2) -> str:
    """Format a BRL amount with two decimals, e.g. R$ 1,234.56 ('–' when missing)."""
    if value is None or pd.isna(value):
        return "–"
    return f"R$ {value:,.{decimals}f}"


def brl_short(value) -> str:
    """Compact BRL amount for KPI tiles, e.g. R$ 13.54M ('–' when missing)."""
    if value is None or pd.isna(value):
        return "–"
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= div:
            return f"R$ {value / div:,.2f}{suffix}"
    return f"R$ {value:,.2f}"


def num(value, decimals: int = 0) -> str:
    """Format a number with thousands separators ('–' when missing)."""
    if value is None or pd.isna(value):
        return "–"
    return f"{value:,.{decimals}f}"


def pct(value, decimals: int = 1) -> str:
    """Format a 0-1 ratio as a percentage ('–' when missing)."""
    if value is None or pd.isna(value):
        return "–"
    return f"{value * 100:.{decimals}f}%"


def filters():
    """Current global filter values set in streamlit_app.py."""
    s = st.session_state
    return s["f_start"], s["f_end"], tuple(s["f_states"])
