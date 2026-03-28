import streamlit as st
import pandas as pd
from datetime import date
from supabase_client import supabase

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

    # Calculate net quantity per instrument
    df['signed_quantity'] = df.apply(
        lambda r: r['quantity'] if r['type'] in ['buy', 'inflow']
        else -r['quantity'] if r['type'] in ['sell', 'outflow']
        else 0,
        axis=1
    )

    # Calculate average price per instrument (only buy/inflow transactions)
    avg_price = df[df['type'].isin(['buy', 'inflow'])].groupby('isin').apply(
        lambda x: (x['quantity'] * x['price']).sum() / x['quantity'].sum()
    ).reset_index(name='avg_price')

    # Subtract cash when buy happens, add cash when sell happens
    cash_rows = []
    for _, r in df.iterrows():
        if r['type'] == 'buy':
            cash_rows.append({
                'isin': f"cash_{r['currency']}",
                'name': r['currency'],
                'currency': r['currency'],
                'signed_quantity': -(r['quantity'] * r['price'])
            })
        elif r['type'] == 'sell':
            cash_rows.append({
                'isin': f"cash_{r['currency']}",
                'name': r['currency'],
                'currency': r['currency'],
                'signed_quantity': r['quantity'] * r['price']
            })

    positions = df.groupby(['isin', 'name', 'currency'])['signed_quantity'].sum().reset_index()

    if cash_rows:
        cash_df = pd.DataFrame(cash_rows)
        cash_agg = cash_df.groupby(['isin', 'name', 'currency'])['signed_quantity'].sum().reset_index()
        positions = pd.concat([positions, cash_agg]).groupby(['isin', 'name', 'currency'])['signed_quantity'].sum().reset_index()

    positions = positions[positions['signed_quantity'] != 0]

    # Merge average price
    positions = positions.merge(avg_price, on='isin', how='left')

    # For cash, average price is always 1
    positions.loc[positions['isin'].str.startswith('cash_'), 'avg_price'] = 1.0

    # Get asset type from instruments table
    instruments = supabase.table("instruments").select("isin, asset_type").execute()
    inst_df = pd.DataFrame(instruments.data)
    positions = positions.merge(inst_df, on='isin', how='left')

    # For cash positions not in instruments table, set asset_type to 'cash'
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

    # Display header
    st.subheader(f"Portfolio as of {selected_date.strftime('%d/%m/%Y')}")

    # Display one table per asset type
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

    # Grand total
    total = positions['market_value'].sum()
    st.metric("Total Portfolio Value", f"{total:,.2f}")