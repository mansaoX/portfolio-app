import streamlit as st
import pandas as pd
from datetime import date
from supabase_client import supabase
from engine.calculations import apply_transaction_to_positions, apply_splits

st.set_page_config(page_title="Portfolio Manager", layout="wide")
st.title("Portfolio Manager")

# --- Select Account ---
accounts = supabase.table("accounts").select("account_id, account_number, client_name").execute()
account_options = {f"{a['account_number']} - {a['client_name']}": a['account_number'] for a in accounts.data}

selected_label = st.selectbox("Select Account", list(account_options.keys()))
selected_account_id = account_options[selected_label]

# --- Select Date ---
selected_date = st.date_input("Valuation Date", value=date.today())

# --- Load Transactions up to selected date ---
transactions = supabase.table("transactions")\
    .select("isin, name, type, quantity, price, currency, fx_rate_to_ref, date")\
    .eq("account_number", str(selected_account_id))\
    .lte("date", selected_date.strftime('%Y-%m-%d'))\
    .execute()

if not transactions.data:
    st.warning("No transactions found for this account up to this date.")
else:
    df = pd.DataFrame(transactions.data)

    # --- Average price (buy/inflow/transfer_in only) ---
    avg_price = df[df['type'].isin(['buy', 'inflow', 'transfer_in'])].groupby('isin').apply(
        lambda x: (x['quantity'] * x['price']).sum() / x['quantity'].sum()
    ).reset_index(name='avg_price')

    # --- Calculate positions ---
    df_no_splits = df[df['type'] != 'split']
    splits_df = df[df['type'] == 'split'][['isin', 'quantity']].copy()

    movements = apply_transaction_to_positions(df_no_splits)

    if movements.empty:
        st.warning("No position data found.")
    else:
        positions = movements.groupby(['isin', 'currency', 'fx_rate_to_ref'])['signed_quantity'].sum().reset_index()

        # Apply splits
        if not splits_df.empty:
            positions = apply_splits(positions, splits_df)

        # Merge name from transactions
        names = df[['isin', 'name']].drop_duplicates('isin')
        positions = positions.merge(names, on='isin', how='left')

        positions = positions[positions['signed_quantity'] != 0]

        # Merge average price
        positions = positions.merge(avg_price, on='isin', how='left')
        positions.loc[positions['isin'].str.startswith('cash_'), 'avg_price'] = 1.0

        # Get asset type from instruments table
        instruments = supabase.table("instruments").select("isin, asset_type").execute()
        inst_df = pd.DataFrame(instruments.data)
        positions = positions.merge(inst_df, on='isin', how='left')
        positions.loc[positions['isin'].str.startswith('cash_'), 'asset_type'] = 'cash'
        positions['asset_type'] = positions['asset_type'].fillna('unknown')

        # Get latest price per instrument on or before selected date
        prices_list = []
        for _, row in positions.iterrows():
            price = supabase.table("prices")\
                .select("price, date")\
                .eq("isin", row['isin'])\
                .lte("date", selected_date.strftime('%Y-%m-%d'))\
                .order("date", desc=True)\
                .limit(1)\
                .execute()
            if price.data:
                prices_list.append({
                    "isin": row['isin'],
                    "last_price": price.data[0]['price'],
                    "price_date": price.data[0]['date']
                })
            elif row['isin'].startswith('cash_'):
                prices_list.append({
                    "isin": row['isin'],
                    "last_price": 1.0,
                    "price_date": str(selected_date)
                })
            else:
                prices_list.append({
                    "isin": row['isin'],
                    "last_price": None,
                    "price_date": None
                })

        prices_df = pd.DataFrame(prices_list)
        positions = positions.merge(prices_df, on='isin', how='left')

        # Calculate market value
        positions['market_value'] = positions['signed_quantity'] * positions['last_price']

        # Format price date for display
        positions['price_date'] = pd.to_datetime(positions['price_date']).dt.strftime('%d/%m/%Y')

        # Display
        st.subheader(f"Portfolio as of {selected_date.strftime('%d/%m/%Y')}")

        for asset_type in sorted(positions['asset_type'].unique()):
            st.markdown(f"### {asset_type.upper()}")
            subset = positions[positions['asset_type'] == asset_type][
                ['name', 'isin', 'signed_quantity', 'avg_price', 'last_price', 'price_date', 'currency', 'market_value']
            ].rename(columns={
                'name': 'Instrument',
                'isin': 'ISIN',
                'signed_quantity': 'Quantity',
                'avg_price': 'Avg Price',
                'last_price': 'Last Price',
                'price_date': 'Price Date',
                'currency': 'Currency',
                'market_value': 'Market Value'
            })
            st.dataframe(subset, use_container_width=True, hide_index=True)
            subtotal = positions[positions['asset_type'] == asset_type]['market_value'].sum()
            st.caption(f"Subtotal: {subtotal:,.2f}")

        total = positions['market_value'].sum()
        st.metric("Total Portfolio Value", f"{total:,.2f}")