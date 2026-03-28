import streamlit as st
import pandas as pd
from supabase_client import supabase

st.set_page_config(page_title="Manage Accounts & Instruments", layout="wide")
st.title("Manage Accounts & Instruments")

tab1, tab2 = st.tabs(["Accounts", "Instruments"])

# ── ACCOUNTS ──────────────────────────────────────────────
with tab1:
    st.subheader("Existing Accounts")
    accounts = supabase.table("accounts")\
        .select("account_number, client_name, bank_name, reference_currency, inception_date")\
        .execute()
    if accounts.data:
        acc_df = pd.DataFrame(accounts.data)
        acc_df['inception_date'] = pd.to_datetime(acc_df['inception_date']).dt.strftime('%d/%m/%Y')
        st.dataframe(acc_df, use_container_width=True, hide_index=True)
    else:
        st.info("No accounts yet.")

    st.subheader("Add New Account")
    col1, col2 = st.columns(2)
    with col1:
        acc_number = st.text_input("Account Number (e.g. UBS-001)")
        client_name = st.text_input("Client Name")
        bank_name = st.text_input("Bank Name")
    with col2:
        ref_currency = st.selectbox("Reference Currency", ["USD", "EUR", "CHF", "GBP", "JPY"])
        inception_date = st.date_input("Inception Date")

    if st.button("Add Account", type="primary"):
        try:
            supabase.table("accounts").insert({
                "account_number": acc_number,
                "client_name": client_name,
                "bank_name": bank_name,
                "reference_currency": ref_currency,
                "inception_date": str(inception_date)
            }).execute()
            st.success(f"Account {acc_number} added!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")

# ── INSTRUMENTS ───────────────────────────────────────────
with tab2:
    st.subheader("Existing Instruments")
    instruments = supabase.table("instruments")\
        .select("isin, internal_code, name, asset_type, currency, has_daily_nav, yahoo_ticker")\
        .execute()
    if instruments.data:
        inst_df = pd.DataFrame(instruments.data)
        st.dataframe(inst_df, use_container_width=True, hide_index=True)
    else:
        st.info("No instruments yet.")

    st.subheader("Add New Instrument")
    col1, col2 = st.columns(2)
    with col1:
        isin = st.text_input("ISIN (optional)")
        internal_code = st.text_input("Internal Code (e.g. AAPL or HF-BRIDGEWATER)")
        inst_name = st.text_input("Name")
        asset_type = st.selectbox("Asset Type", 
            ["stock", "etf", "bond", "mutual_fund", "hedge_fund", "cash", "other"])
    with col2:
        inst_currency = st.selectbox("Currency", ["USD", "EUR", "CHF", "GBP", "JPY", "other"])
        has_nav = st.checkbox("Has Daily NAV", value=True)
        yahoo_ticker = st.text_input("Yahoo Finance Ticker (leave empty for hedge funds)")

    if st.button("Add Instrument", type="primary"):
        try:
            supabase.table("instruments").insert({
                "isin": isin if isin else None,
                "internal_code": internal_code,
                "name": inst_name,
                "asset_type": asset_type,
                "currency": inst_currency,
                "has_daily_nav": has_nav,
                "yahoo_ticker": yahoo_ticker if yahoo_ticker else None
            }).execute()
            st.success(f"Instrument {inst_name} added!")
            st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")