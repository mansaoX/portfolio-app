import streamlit as st
import pandas as pd
from supabase_client import supabase

st.set_page_config(page_title="Import Transactions", layout="wide")
st.title("Import Transactions")

st.info("Upload a bank Excel or CSV file. Required columns: account_number, isin, name, date, type, quantity, price, currency, fx_rate_to_ref")

uploaded_file = st.file_uploader("Choose a file", type=["xlsx", "csv"])

if uploaded_file:
    # Read file
    if uploaded_file.name.endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)

    st.subheader("Preview")
    st.dataframe(df.head(10), use_container_width=True)

    # Validate columns
    required_cols = ['account_number', 'isin', 'name', 'date', 'type', 'quantity', 'price', 'currency', 'fx_rate_to_ref']
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.error(f"Missing columns: {', '.join(missing)}")
    else:
        # Convert date
        df['date'] = pd.to_datetime(df['date'], dayfirst=True).dt.strftime('%Y-%m-%d')
        df = df.where(pd.notnull(df), None)

        st.success(f"{len(df)} rows ready to import.")

        # Check for duplicates against existing transactions
        st.subheader("Duplicate Check")
        existing = supabase.table("transactions")\
            .select("account_number, isin, date, type, quantity")\
            .execute()
        existing_df = pd.DataFrame(existing.data)

        if not existing_df.empty:
            merged = df.merge(existing_df, on=['account_number', 'isin', 'date', 'type', 'quantity'], how='left', indicator=True)
            duplicates = merged[merged['_merge'] == 'both']
            new_rows = merged[merged['_merge'] == 'left_only'].drop(columns=['_merge'])
            st.write(f"New rows: {len(new_rows)} | Duplicates skipped: {len(duplicates)}")
        else:
            new_rows = df

        if st.button("Import", type="primary"):
            success = 0
            errors = 0
            for _, row in new_rows.iterrows():
                try:
                    record = {
                        "account_number": str(row['account_number']),
                        "isin": str(row['isin']),
                        "name": str(row['name']),
                        "date": row['date'],
                        "type": str(row['type']),
                        "quantity": float(row['quantity']) if row['quantity'] is not None else None,
                        "price": float(row['price']) if row['price'] is not None else None,
                        "currency": str(row['currency']),
                        "fx_rate_to_ref": float(row['fx_rate_to_ref']) if row['fx_rate_to_ref'] is not None else 1.0,
                    }
                    supabase.table("transactions").insert(record).execute()
                    success += 1
                except Exception as e:
                    errors += 1
                    st.error(f"Error on row {_}: {e}")

            st.success(f"Done! {success} transactions imported, {errors} errors.")