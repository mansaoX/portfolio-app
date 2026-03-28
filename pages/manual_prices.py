import streamlit as st
import pandas as pd
from datetime import date
from supabase_client import supabase

st.set_page_config(page_title="Manual Price Entry", layout="wide")
st.title("Manual Price Entry")
st.info("Use this page to enter prices for hedge funds and other instruments without automatic pricing.")

# --- Fetch instruments without yahoo_ticker (manual pricing only) ---
instruments = supabase.table("instruments").select("isin, name, asset_type, currency, yahoo_ticker").execute()
inst_df = pd.DataFrame(instruments.data)

if inst_df.empty:
    st.warning("No instruments found. Add instruments first.")
else:
    # Filter to manual-only instruments (no yahoo ticker)
    manual_inst = inst_df[inst_df['yahoo_ticker'].isna() | (inst_df['yahoo_ticker'] == '')]
    all_inst = inst_df

    tab1, tab2 = st.tabs(["Enter New Price", "View/Edit Existing Prices"])

    with tab1:
        col1, col2 = st.columns([2, 1])
        with col1:
            show_all = st.checkbox("Show all instruments (including auto-priced)")
            display_inst = all_inst if show_all else manual_inst
            if display_inst.empty:
                st.info("No manual instruments found.")
            else:
                inst_options = {f"{r['name']} ({r['isin']})": r['isin'] for _, r in display_inst.iterrows()}
                selected_inst = st.selectbox("Instrument", list(inst_options.keys()))
                selected_isin = inst_options[selected_inst]
                selected_ccy = display_inst[display_inst['isin'] == selected_isin]['currency'].iloc[0]

        with col2:
            price_date = st.date_input("Price Date", value=date.today())
            price_value = st.number_input("Price", min_value=0.0, format="%.4f")

        if st.button("Save Price", type="primary"):
            try:
                supabase.table("prices").upsert({
                    "isin": selected_isin,
                    "date": str(price_date),
                    "price": price_value,
                    "currency": selected_ccy,
                    "source": "manual"
                }).execute()
                st.success(f"Price saved: {selected_inst} = {price_value} on {price_date.strftime('%d/%m/%Y')}")
            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        inst_options2 = {f"{r['name']} ({r['isin']})": r['isin'] for _, r in all_inst.iterrows()}
        selected_inst2 = st.selectbox("Select Instrument", list(inst_options2.keys()), key="view_inst")
        selected_isin2 = inst_options2[selected_inst2]

        prices = supabase.table("prices")\
            .select("*")\
            .eq("isin", selected_isin2)\
            .order("date", desc=True)\
            .limit(50)\
            .execute()

        if prices.data:
            prices_df = pd.DataFrame(prices.data)
            prices_df['date'] = pd.to_datetime(prices_df['date']).dt.strftime('%d/%m/%Y')
            st.dataframe(prices_df[['date', 'price', 'currency', 'source']], 
                        use_container_width=True, hide_index=True)
        else:
            st.info("No prices found for this instrument.")