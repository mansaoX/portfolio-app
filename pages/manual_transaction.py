import streamlit as st
import pandas as pd
from datetime import date
from supabase_client import supabase

st.set_page_config(page_title="Manual Transaction Entry", layout="wide")
st.title("Manual Transaction Entry")

# Load accounts and instruments
accounts = supabase.table("accounts").select("account_number, client_name").execute()
account_options = {f"{a['account_number']} - {a['client_name']}": a['account_number'] for a in accounts.data}

instruments = supabase.table("instruments").select("isin, name, currency").execute()
inst_options = {f"{i['name']} ({i['isin'] or 'no ISIN'})": i for i in instruments.data}

col1, col2 = st.columns(2)

with col1:
    selected_account = st.selectbox("Account", list(account_options.keys()))
    account_number = account_options[selected_account]

    selected_inst_label = st.selectbox("Instrument", list(inst_options.keys()))
    selected_inst = inst_options[selected_inst_label]
    isin = selected_inst['isin']
    name = selected_inst_label.split(' (')[0]
    currency = selected_inst['currency']

    transaction_date = st.date_input("Date", value=date.today())
    transaction_type = st.selectbox("Type", 
        ["buy", "sell", "inflow", "outflow", "dividend", 
         "coupon", "fee", "fx", "split", "transfer_in", "transfer_out"])

with col2:
    quantity = st.number_input("Quantity", min_value=0.0, format="%.4f")
    price = st.number_input("Price", min_value=0.0, format="%.4f", value=1.0)
    fx_rate = st.number_input("FX Rate to Reference Currency", 
                               min_value=0.0, format="%.6f", value=1.0)
    bank_reference = st.text_input("Bank Reference (optional)")

    st.markdown("")
    st.markdown(f"**Total amount: {quantity * price:,.2f} {currency}**")
    st.markdown(f"**In ref currency: {quantity * price * fx_rate:,.2f}**")

if st.button("Save Transaction", type="primary"):
    try:
        supabase.table("transactions").insert({
            "account_number": account_number,
            "isin": isin,
            "name": name,
            "date": str(transaction_date),
            "type": transaction_type,
            "quantity": float(quantity),
            "price": float(price),
            "currency": currency,
            "fx_rate_to_ref": float(fx_rate),
        }).execute()
        st.success("Transaction saved successfully!")
    except Exception as e:
        st.error(f"Error: {e}")

# --- Recent transactions ---
st.subheader("Recent Transactions")
recent = supabase.table("transactions")\
    .select("*")\
    .eq("account_number", account_number)\
    .order("date", desc=True)\
    .limit(10)\
    .execute()
if recent.data:
    recent_df = pd.DataFrame(recent.data)
    recent_df['date'] = pd.to_datetime(recent_df['date']).dt.strftime('%d/%m/%Y')
    st.dataframe(recent_df[['date', 'name', 'isin', 'type', 'quantity', 'price', 'currency', 'fx_rate_to_ref']], 
                use_container_width=True, hide_index=True)