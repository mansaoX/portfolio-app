import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import date, timedelta
from supabase_client import supabase
from engine.calculations import calculate_twr, calculate_mwr, calculate_contributions, get_portfolio_value

st.set_page_config(page_title="Performance Report", layout="wide")
st.title("Performance Report")

# --- Common indices list for searchable dropdown ---
INDEX_OPTIONS = {
    "MSCI World (URTH)": "URTH",
    "S&P 500 (SPY)": "SPY",
    "S&P 500 (^GSPC)": "^GSPC",
    "Nasdaq 100 (QQQ)": "QQQ",
    "Euro Stoxx 50 (FEZ)": "FEZ",
    "Euro Stoxx 50 (^STOXX50E)": "^STOXX50E",
    "Swiss Market Index (EWL)": "EWL",
    "SMI (^SSMI)": "^SSMI",
    "FTSE 100 (^FTSE)": "^FTSE",
    "DAX (^GDAXI)": "^GDAXI",
    "CAC 40 (^FCHI)": "^FCHI",
    "Nikkei 225 (^N225)": "^N225",
    "Emerging Markets (EEM)": "EEM",
    "Bloomberg Bonds (AGG)": "AGG",
    "US Treasury 10Y (IEF)": "IEF",
    "Gold (GLD)": "GLD",
    "None (no benchmark)": None
}

# --- Top controls on same line ---
col_acct, col_month = st.columns([2, 1])

with col_acct:
    accounts = supabase.table("accounts").select("account_number, client_name, inception_date").execute()
    account_options = {f"{a['account_number']} - {a['client_name']}": a for a in accounts.data}
    selected_label = st.selectbox("Account", list(account_options.keys()))

with col_month:
    today = date.today()
    report_month = st.date_input("Report Month", value=today.replace(day=1))

# --- Index selector on its own line but narrow ---
col_idx, col_empty = st.columns([2, 3])
with col_idx:
    selected_index_label = st.selectbox(
        "Benchmark Index",
        list(INDEX_OPTIONS.keys()),
        index=len(INDEX_OPTIONS) - 1  # default to None
    )
selected_ticker = INDEX_OPTIONS[selected_index_label]

selected_account = account_options[selected_label]
account_number = selected_account['account_number']
inception_date = pd.to_datetime(selected_account['inception_date']).date()

mtd_start = report_month.replace(day=1)
mtd_end = (report_month.replace(day=1) + pd.offsets.MonthEnd(1)).date()
mtd_end = min(mtd_end, today)
ytd_start = max(date(report_month.year, 1, 1), inception_date)
itd_start = inception_date

def fetch_index_twr(ticker, start, end):
    """Fetch index prices from Yahoo Finance and compute cumulative TWR."""
    try:
        data = yf.download(ticker, start=start - timedelta(days=5), end=end + timedelta(days=1), progress=False)
        if data.empty:
            return None, None
        prices = data['Close'].squeeze()
        prices.index = pd.to_datetime(prices.index).tz_localize(None)
        all_dates = pd.date_range(start=start, end=end)
        prices = prices.reindex(prices.index.union(all_dates)).ffill()
        prices = prices[prices.index >= pd.Timestamp(start)]
        prices = prices[prices.index <= pd.Timestamp(end)]
        base = prices.iloc[0]
        cumulative = (prices / base - 1) * 100
        final_twr = float(prices.iloc[-1] / base - 1)
        return cumulative, final_twr
    except:
        return None, None

# --- Options ---
col_opt1, col_opt2 = st.columns([1, 4])
with col_opt1:
    include_itd = st.checkbox("Include Inception to Date", value=False)

if st.button("Generate Report", type="primary"):

    # Count total steps for progress bar
    total_steps = 5 if not include_itd else 7
    step = 0
    progress = st.progress(0, text="Starting...")

    def advance(msg):
        global step
        step += 1
        progress.progress(int(step / total_steps * 100), text=msg)

    # --- Calculate TWR ---
    advance("Calculating MTD TWR...")
    twr_mtd_df = calculate_twr(supabase, account_number, mtd_start, mtd_end)
    twr_mtd = twr_mtd_df['cumulative_twr'].iloc[-1] if not twr_mtd_df.empty else 0

    advance("Calculating YTD TWR...")
    twr_ytd_df = calculate_twr(supabase, account_number, ytd_start, mtd_end)
    twr_ytd = twr_ytd_df['cumulative_twr'].iloc[-1] if not twr_ytd_df.empty else 0

    twr_itd_df = pd.DataFrame()
    twr_itd = 0
    if include_itd:
        advance("Calculating ITD TWR...")
        twr_itd_df = calculate_twr(supabase, account_number, itd_start, mtd_end)
        twr_itd = twr_itd_df['cumulative_twr'].iloc[-1] if not twr_itd_df.empty else 0

    # --- Calculate MWR ---
    advance("Calculating MWR...")
    mwr_mtd = calculate_mwr(supabase, account_number, mtd_start, mtd_end)
    mwr_ytd = calculate_mwr(supabase, account_number, ytd_start, mtd_end)
    mwr_itd = calculate_mwr(supabase, account_number, itd_start, mtd_end) if include_itd else None

    # --- Portfolio Value ---
    portfolio_value = get_portfolio_value(supabase, account_number, mtd_end)

    # --- Fetch Index ---
    advance("Fetching benchmark index...")
    idx_mtd, idx_mtd_val = (None, None)
    idx_ytd, idx_ytd_val = (None, None)
    idx_itd, idx_itd_val = (None, None)
    if selected_ticker:
        idx_mtd, idx_mtd_val = fetch_index_twr(selected_ticker, mtd_start, mtd_end)
        idx_ytd, idx_ytd_val = fetch_index_twr(selected_ticker, ytd_start, mtd_end)
        if include_itd:
            idx_itd, idx_itd_val = fetch_index_twr(selected_ticker, itd_start, mtd_end)

    # --- Contributions ---
    advance("Calculating contributions...")
    contributions = calculate_contributions(supabase, account_number, mtd_start, mtd_end)

    progress.progress(100, text="Done!")

    # --- Performance Summary Table ---
    st.subheader("Performance Summary")

    def fmt(v):
        return f"{v*100:.2f}%" if v is not None else "N/A"

    summary_data = {
        "": ["Portfolio TWR", "Portfolio MWR", f"Index ({selected_index_label})" if selected_ticker else "Index"],
        "MTD": [fmt(twr_mtd), fmt(mwr_mtd), fmt(idx_mtd_val)],
        "YTD": [fmt(twr_ytd), fmt(mwr_ytd), fmt(idx_ytd_val)],
    }
    if include_itd:
        summary_data["ITD"] = [fmt(twr_itd), fmt(mwr_itd), fmt(idx_itd_val)]
    summary_data["Portfolio Value"] = [f"{portfolio_value:,.2f}", "", ""]

    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, use_container_width=False, hide_index=True)

    # --- TWR Chart ---
    st.subheader("Performance Chart")
    fig = go.Figure()

    # Use YTD if ITD not selected, ITD if selected
    chart_df = twr_itd_df if include_itd else twr_ytd_df
    chart_label = "Inception to Date" if include_itd else "Year to Date"
    idx_chart = idx_itd if include_itd else idx_ytd

    fig.add_trace(go.Scatter(
        x=chart_df['date'],
        y=(chart_df['cumulative_twr'] * 100).round(2),
        mode='lines',
        name='Portfolio TWR',
        line=dict(color='#00b4d8', width=2)
    ))

    if selected_ticker and idx_chart is not None:
        fig.add_trace(go.Scatter(
            x=idx_chart.index,
            y=idx_chart.round(2),
            mode='lines',
            name=selected_index_label,
            line=dict(color='#ff9f1c', width=2, dash='dash')
        ))

    fig.update_layout(
        title=chart_label,
        yaxis_title="Return (%)",
        xaxis_title="Date",
        hovermode="x unified",
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)',
        yaxis=dict(ticksuffix="%"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    st.plotly_chart(fig, use_container_width=True)

    # --- Monthly TWR Table ---
    st.subheader("Monthly TWR")
    base_df = twr_itd_df if include_itd else twr_ytd_df
    base_df['year'] = base_df['date'].dt.year
    base_df['month'] = base_df['date'].dt.month

    monthly = base_df.groupby(['year', 'month']).apply(
        lambda x: ((1 + x['daily_return']).prod() - 1) * 100
    ).reset_index(name='monthly_twr')

    month_names = {1:'Jan',2:'Feb',3:'Mar',4:'Apr',5:'May',6:'Jun',
                   7:'Jul',8:'Aug',9:'Sep',10:'Oct',11:'Nov',12:'Dec'}
    monthly['month'] = monthly['month'].map(month_names)
    monthly_pivot = monthly.pivot(index='year', columns='month', values='monthly_twr')
    ordered_cols = [m for m in month_names.values() if m in monthly_pivot.columns]
    monthly_pivot = monthly_pivot[ordered_cols]
    monthly_pivot['YTD'] = monthly_pivot.apply(
        lambda row: ((1 + row.dropna()/100).prod() - 1) * 100, axis=1
    )
    st.dataframe(monthly_pivot.round(2).style.format("{:.2f}%"), use_container_width=True)

    # --- Contributions by Instrument grouped by Asset Type ---
    st.subheader("Contribution by Instrument (MTD)")

    if not contributions.empty:
        instruments = supabase.table("instruments").select("isin, asset_type").execute()
        inst_df = pd.DataFrame(instruments.data)
        contributions = contributions.merge(inst_df, left_on='ISIN', right_on='isin', how='left')
        contributions.loc[contributions['ISIN'].str.startswith('cash_'), 'asset_type'] = 'cash'
        contributions['asset_type'] = contributions['asset_type'].fillna('unknown')

        for asset_type in sorted(contributions['asset_type'].unique()):
            st.markdown(f"**{asset_type.upper()}**")
            subset = contributions[contributions['asset_type'] == asset_type][
                ['Instrument', 'ISIN', 'P&L', 'Contribution']
            ].copy()
            subtotal_pnl = subset['P&L'].sum()
            subtotal_contrib = subset['Contribution'].sum()
            subset['P&L'] = subset['P&L'].map("{:,.2f}".format)
            subset['Contribution'] = subset['Contribution'].map("{:.4f}%".format)
            st.dataframe(subset, use_container_width=True, hide_index=True)
            st.caption(f"Subtotal — P&L: {subtotal_pnl:,.2f} | Contribution: {subtotal_contrib:.4f}%")

        total_pnl = contributions['P&L'].sum()
        total_contrib = contributions['Contribution'].sum()
        st.markdown(f"**Total — P&L: {total_pnl:,.2f} | Contribution: {total_contrib:.4f}%**")