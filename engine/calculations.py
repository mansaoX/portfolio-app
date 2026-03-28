import pandas as pd
import numpy as np
from datetime import date, timedelta
from scipy.optimize import brentq

def apply_transaction_to_positions(df):
    """Convert raw transactions into signed quantities and cash impacts."""
    
    rows = []
    cash_rows = []
    
    for _, r in df.iterrows():
        isin = r['isin']
        qty = r['quantity'] if r['quantity'] else 0
        price = r['price'] if r['price'] else 0
        ccy = r['currency']
        fx = r['fx_rate_to_ref'] if r['fx_rate_to_ref'] else 1.0
        cash_isin = f"cash_{ccy}"

        if r['type'] == 'buy':
            rows.append({'isin': isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty})
            cash_rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -(qty * price)})

        elif r['type'] == 'sell':
            rows.append({'isin': isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -qty})
            cash_rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty * price})

        elif r['type'] == 'inflow':
            rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty * price})

        elif r['type'] == 'outflow':
            rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -(qty * price)})

        elif r['type'] in ['dividend', 'coupon']:
            cash_rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty * price})

        elif r['type'] == 'fee':
            cash_rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -(qty * price)})

        elif r['type'] == 'fx':
            # quantity = amount of source currency sold, price = fx rate to target currency
            # isin = source cash, name field should contain target currency
            target_ccy = r.get('name', ccy)
            rows.append({'isin': cash_isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -qty})
            rows.append({'isin': f"cash_{target_ccy}", 'currency': target_ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty * price})

        elif r['type'] == 'split':
            # quantity = split ratio (e.g. 2 means 2-for-1)
            # We need current quantity before split — handled separately in portfolio view
            rows.append({'isin': isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty, 'is_split': True})

        elif r['type'] == 'transfer_in':
            rows.append({'isin': isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': qty})

        elif r['type'] == 'transfer_out':
            rows.append({'isin': isin, 'currency': ccy, 'fx_rate_to_ref': fx, 'signed_quantity': -qty})

    all_rows = rows + cash_rows
    return pd.DataFrame(all_rows) if all_rows else pd.DataFrame(
        columns=['isin', 'currency', 'fx_rate_to_ref', 'signed_quantity'])


def apply_splits(positions_df, splits_df):
    """Apply stock splits to existing positions."""
    if splits_df.empty:
        return positions_df
    for _, split in splits_df.iterrows():
        mask = positions_df['isin'] == split['isin']
        positions_df.loc[mask, 'signed_quantity'] *= split['quantity']
    return positions_df


def get_portfolio_value(supabase, account_number, valuation_date):
    """Calculate total portfolio value in account reference currency for a given date."""

    transactions = supabase.table("transactions")\
        .select("isin, name, type, quantity, price, currency, fx_rate_to_ref, date")\
        .eq("account_number", account_number)\
        .lte("date", str(valuation_date))\
        .execute()

    if not transactions.data:
        return 0.0

    df = pd.DataFrame(transactions.data)

    # Separate splits
    splits_df = df[df['type'] == 'split'][['isin', 'quantity']].copy()
    splits_df = splits_df.rename(columns={'quantity': 'quantity'})
    df_no_splits = df[df['type'] != 'split']

    movements = apply_transaction_to_positions(df_no_splits)
    if movements.empty:
        return 0.0

    positions = movements.groupby(['isin', 'currency', 'fx_rate_to_ref'])['signed_quantity'].sum().reset_index()

    # Apply splits
    if not splits_df.empty:
        positions = apply_splits(positions, splits_df)

    positions = positions[positions['signed_quantity'] != 0]

    total = 0.0
    for _, row in positions.iterrows():
        if row['isin'].startswith('cash_'):
            price = 1.0
        else:
            p = supabase.table("prices")\
                .select("price")\
                .eq("isin", row['isin'])\
                .lte("date", str(valuation_date))\
                .order("date", desc=True)\
                .limit(1)\
                .execute()
            price = p.data[0]['price'] if p.data else None

        if price is not None:
            total += row['signed_quantity'] * price * row['fx_rate_to_ref']

    return total


def get_cash_flows(supabase, account_number, start_date, end_date):
    """Get external cash flows (deposits, withdrawals, transfers) between two dates."""

    external_types = ['inflow', 'outflow', 'transfer_in', 'transfer_out']

    transactions = supabase.table("transactions")\
        .select("date, type, quantity, price, fx_rate_to_ref")\
        .eq("account_number", account_number)\
        .in_("type", external_types)\
        .gte("date", str(start_date))\
        .lte("date", str(end_date))\
        .execute()

    flows = []
    for t in transactions.data:
        qty = t['quantity'] if t['quantity'] else 0
        price = t['price'] if t['price'] else 1.0
        fx = t['fx_rate_to_ref'] if t['fx_rate_to_ref'] else 1.0
        amount = qty * price * fx
        if t['type'] in ['outflow', 'transfer_out']:
            amount = -amount
        flows.append({'date': pd.to_datetime(t['date']), 'amount': amount})

    return pd.DataFrame(flows) if flows else pd.DataFrame(columns=['date', 'amount'])


def calculate_twr(supabase, account_number, start_date, end_date):
    """Calculate TWR by chaining daily returns."""

    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    cash_flows = get_cash_flows(supabase, account_number, start_date, end_date)

    daily_returns = []
    prev_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    cumulative_twr = 1.0

    for current_date in all_dates:
        day_cf = cash_flows[cash_flows['date'] == current_date]['amount'].sum() \
            if not cash_flows.empty else 0.0
        end_value = get_portfolio_value(supabase, account_number, current_date.date())
        denominator = prev_value + day_cf
        daily_return = (end_value / denominator) - 1 if denominator > 0 else 0.0
        cumulative_twr *= (1 + daily_return)

        daily_returns.append({
            'date': current_date,
            'daily_return': daily_return,
            'cumulative_twr': cumulative_twr - 1,
            'portfolio_value': end_value
        })
        prev_value = end_value

    return pd.DataFrame(daily_returns)


def calculate_mwr(supabase, account_number, start_date, end_date):
    """Calculate MWR (IRR / Money-Weighted Return)."""

    start_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    end_value = get_portfolio_value(supabase, account_number, end_date)
    cash_flows = get_cash_flows(supabase, account_number, start_date, end_date)
    total_days = (end_date - start_date).days

    cf_list = [(-start_value, 0)]
    for _, row in cash_flows.iterrows():
        days = (row['date'].date() - start_date).days
        cf_list.append((-row['amount'], days))
    cf_list.append((end_value, total_days))

    def npv(rate):
        return sum(cf * ((1 + rate) ** (-d / 365)) for cf, d in cf_list)

    try:
        mwr = brentq(npv, -0.999, 10.0)
        return mwr
    except:
        return None


def calculate_contributions(supabase, account_number, start_date, end_date):
    """Calculate performance contribution by instrument."""

    transactions = supabase.table("transactions")\
        .select("isin, name, type, quantity, price, currency, fx_rate_to_ref, date")\
        .eq("account_number", account_number)\
        .lte("date", str(end_date))\
        .execute()

    if not transactions.data:
        return pd.DataFrame()

    df = pd.DataFrame(transactions.data)
    df['date'] = pd.to_datetime(df['date'])

    start_portfolio_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    if start_portfolio_value == 0:
        return pd.DataFrame()

    contributions = []
    isins = df['isin'].unique()

    for isin in isins:
        inst_df = df[df['isin'] == isin]
        name = inst_df['name'].iloc[0]
        fx = inst_df['fx_rate_to_ref'].iloc[-1]

        # Quantity at start
        df_start = inst_df[inst_df['date'] <= pd.Timestamp(start_date)]
        splits_start = df_start[df_start['type'] == 'split'][['isin', 'quantity']].copy()
        df_start_no_split = df_start[df_start['type'] != 'split']
        mv_start = apply_transaction_to_positions(df_start_no_split)
        qty_start = mv_start.groupby('isin')['signed_quantity'].sum().get(isin, 0) if not mv_start.empty else 0

        p_start = supabase.table("prices").select("price")\
            .eq("isin", isin).lte("date", str(start_date))\
            .order("date", desc=True).limit(1).execute()
        price_start = p_start.data[0]['price'] if p_start.data else (1.0 if isin.startswith('cash_') else None)
        value_start = qty_start * price_start * fx if price_start else 0

        # Quantity at end
        df_end = inst_df[inst_df['date'] <= pd.Timestamp(end_date)]
        splits_end = df_end[df_end['type'] == 'split'][['isin', 'quantity']].copy()
        df_end_no_split = df_end[df_end['type'] != 'split']
        mv_end = apply_transaction_to_positions(df_end_no_split)
        qty_end = mv_end.groupby('isin')['signed_quantity'].sum().get(isin, 0) if not mv_end.empty else 0

        p_end = supabase.table("prices").select("price")\
            .eq("isin", isin).lte("date", str(end_date))\
            .order("date", desc=True).limit(1).execute()
        price_end = p_end.data[0]['price'] if p_end.data else (1.0 if isin.startswith('cash_') else None)
        value_end = qty_end * price_end * fx if price_end else 0

        # Cash flows for this instrument during period
        inst_flows = inst_df[
            (inst_df['date'] > pd.Timestamp(start_date)) &
            (inst_df['date'] <= pd.Timestamp(end_date)) &
            (inst_df['type'].isin(['inflow', 'outflow', 'transfer_in', 'transfer_out']))
        ]
        net_flow = 0
        for _, r in inst_flows.iterrows():
            amt = r['quantity'] * r['price'] * r['fx_rate_to_ref']
            net_flow += amt if r['type'] in ['inflow', 'transfer_in'] else -amt

        pnl = value_end - value_start - net_flow
        contribution = pnl / start_portfolio_value

        contributions.append({
            'Instrument': name,
            'ISIN': isin,
            'P&L': round(pnl, 2),
            'Contribution': round(contribution * 100, 4)
        })

    return pd.DataFrame(contributions).sort_values('Contribution', ascending=False)