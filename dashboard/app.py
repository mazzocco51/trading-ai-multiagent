import os

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./paper_trading.db")

st.set_page_config(page_title="Trading AI Multi-Agent", layout="wide")
st.title("Trading AI Multi-Agent — Paper Dashboard")

@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL)

engine = get_engine()

# Equity curve
st.subheader("Equity Curve")
try:
    eq_df = pd.read_sql(
        "SELECT timestamp, balance FROM equity_snapshots ORDER BY timestamp DESC LIMIT 200",
        engine,
    )
    if not eq_df.empty:
        eq_df = eq_df.sort_values("timestamp")
        st.line_chart(eq_df.set_index("timestamp")["balance"])
    else:
        st.info("No equity data yet.")
except Exception as e:
    st.warning(f"DB not ready: {e}")

# Recent decisions
st.subheader("Recent Decisions")
try:
    dec_df = pd.read_sql(
        """
        SELECT d.timestamp, d.asset, d.action, d.conviction,
               d.veto, d.veto_reason, d.combined_rationale
        FROM decisions d
        ORDER BY d.timestamp DESC LIMIT 50
        """,
        engine,
    )
    if not dec_df.empty:
        st.dataframe(dec_df, use_container_width=True)
    else:
        st.info("No decisions yet.")
except Exception as e:
    st.warning(f"Could not load decisions: {e}")

# Bull vs Bear debates (only populated when DEBATE_ENABLED=true)
st.subheader("Bull vs Bear Debates")
try:
    deb_df = pd.read_sql(
        """
        SELECT b.timestamp, b.asset, d.action, b.bull_summary, b.bear_summary
        FROM debate_logs b
        LEFT JOIN decisions d ON d.id = b.decision_id
        ORDER BY b.timestamp DESC LIMIT 20
        """,
        engine,
    )
    if not deb_df.empty:
        for _, row in deb_df.iterrows():
            with st.expander(f"{row['timestamp']} — {row['asset']} → {row['action']}"):
                col_bull, col_bear = st.columns(2)
                col_bull.markdown(f"**🐂 Bull**\n\n{row['bull_summary']}")
                col_bear.markdown(f"**🐻 Bear**\n\n{row['bear_summary']}")
    else:
        st.info("No debates yet (enable DEBATE_ENABLED=true).")
except Exception as e:
    st.info(f"No debate data: {e}")

# Agent views
st.subheader("Latest Agent Views")
try:
    views_df = pd.read_sql("""
        SELECT v.timestamp, v.asset, v.agent, v.signal, v.confidence, v.rationale
        FROM agent_views_log v
        ORDER BY v.timestamp DESC LIMIT 100
    """, engine)
    if not views_df.empty:
        st.dataframe(views_df, use_container_width=True)
    else:
        st.info("No agent views yet.")
except Exception as e:
    st.warning(f"Could not load agent views: {e}")

st.caption("Data refreshes on page reload. Disclaimer: educational project, paper trading only.")
