import pandas as pd
import numpy as np
from datetime import date, timedelta
from scipy.optimize import brentq

def get_portfolio_value(supabase, account_number, valuation_date):
    """Calculate total portfolio value in account reference currency for a given date."""
    
    transactions = supabase.table("transactions")\
        .select("isin, type, quantity, price, currency, fx_rate_to_ref, date")\
        .eq("account_number", account_number)\
        .lte("date", str(valuation_date))\
        .execute()

    if not transactions.data:
        return 0.0

    df = pd.DataFrame(transactions.data)
    df['signed_quantity'] = df.apply(
        lambda r: r['quantity'] if r['type'] in ['buy', 'inflow']
        else -r['quantity'] if r['type'] in ['sell', 'outflow']
        else 0, axis=1
    )

    # Add cash impact of buys/sells
    cash_rows = []
    for _, r in df.iterrows():
        if r['type'] == 'buy':
            cash_rows.append({'isin': f"cash_{r['currency']}", 'currency': r['currency'],
                             'signed_quantity': -(r['quantity'] * r['price']), 'fx_rate_to_ref': r['fx_rate_to_ref']})
        elif r['type'] == 'sell':
            cash_rows.append({'isin': f"cash_{r['currency']}", 'currency': r['currency'],
                             'signed_quantity': r['quantity'] * r['price'], 'fx_rate_to_ref': r['fx_rate_to_ref']})

    positions = df.groupby(['isin', 'currency', 'fx_rate_to_ref'])['signed_quantity'].sum().reset_index()

    if cash_rows:
        cash_df = pd.DataFrame(cash_rows)
        cash_agg = cash_df.groupby(['isin', 'currency', 'fx_rate_to_ref'])['signed_quantity'].sum().reset_index()
        positions = pd.concat([positions, cash_agg]).groupby(['isin', 'currency', 'fx_rate_to_ref'])['signed_quantity'].sum().reset_index()

    positions = positions[positions['signed_quantity'] != 0]

    # Get prices
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
    """Get external cash flows (deposits and withdrawals) between two dates."""
    
    transactions = supabase.table("transactions")\
        .select("date, type, quantity, price, fx_rate_to_ref")\
        .eq("account_number", account_number)\
        .in_("type", ["inflow", "outflow"])\
        .gte("date", str(start_date))\
        .lte("date", str(end_date))\
        .execute()

    flows = []
    for t in transactions.data:
        amount = t['quantity'] * t['price'] * t['fx_rate_to_ref']
        if t['type'] == 'outflow':
            amount = -amount
        flows.append({'date': pd.to_datetime(t['date']), 'amount': amount})

    return pd.DataFrame(flows) if flows else pd.DataFrame(columns=['date', 'amount'])


def calculate_twr(supabase, account_number, start_date, end_date):
    """
    Calculate TWR by chaining daily returns between start_date and end_date.
    Returns a DataFrame with daily TWR values.
    """
    
    all_dates = pd.date_range(start=start_date, end=end_date, freq='D')
    cash_flows = get_cash_flows(supabase, account_number, start_date, end_date)
    
    daily_returns = []
    prev_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    cumulative_twr = 1.0

    for current_date in all_dates:
        # Get cash flow on this day
        day_cf = cash_flows[cash_flows['date'] == current_date]['amount'].sum() if not cash_flows.empty else 0.0
        
        # Get portfolio value at end of day
        end_value = get_portfolio_value(supabase, account_number, current_date.date())
        
        # Daily TWR = end value / (start value + cash flow)
        denominator = prev_value + day_cf
        if denominator > 0:
            daily_return = (end_value / denominator) - 1
        else:
            daily_return = 0.0

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
    """
    Calculate MWR (IRR / Money-Weighted Return).
    """
    start_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    end_value = get_portfolio_value(supabase, account_number, end_date)
    cash_flows = get_cash_flows(supabase, account_number, start_date, end_date)

    total_days = (end_date - start_date).days

    # Build cash flow list: initial investment as negative, end value as positive
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
    df['signed_quantity'] = df.apply(
        lambda r: r['quantity'] if r['type'] in ['buy', 'inflow']
        else -r['quantity'] if r['type'] in ['sell', 'outflow']
        else 0, axis=1
    )

    start_portfolio_value = get_portfolio_value(supabase, account_number, start_date - timedelta(days=1))
    if start_portfolio_value == 0:
        return pd.DataFrame()

    contributions = []
    isins = df['isin'].unique()

    for isin in isins:
        inst_df = df[df['isin'] == isin]
        name = inst_df['name'].iloc[0]

        # Value at start
        qty_start = inst_df[inst_df['date'] <= pd.Timestamp(start_date)]['signed_quantity'].sum()
        p_start = supabase.table("prices").select("price")\
            .eq("isin", isin).lte("date", str(start_date))\
            .order("date", desc=True).limit(1).execute()
        price_start = p_start.data[0]['price'] if p_start.data else (1.0 if isin.startswith('cash_') else None)
        fx = inst_df['fx_rate_to_ref'].iloc[-1]
        value_start = qty_start * price_start * fx if price_start else 0

        # Value at end
        qty_end = inst_df[inst_df['date'] <= pd.Timestamp(end_date)]['signed_quantity'].sum()
        p_end = supabase.table("prices").select("price")\
            .eq("isin", isin).lte("date", str(end_date))\
            .order("date", desc=True).limit(1).execute()
        price_end = p_end.data[0]['price'] if p_end.data else (1.0 if isin.startswith('cash_') else None)
        value_end = qty_end * price_end * fx if price_end else 0

        # P&L
        pnl = value_end - value_start
        contribution = pnl / start_portfolio_value

        contributions.append({
            'Instrument': name,
            'ISIN': isin,
            'P&L': round(pnl, 2),
            'Contribution': round(contribution * 100, 4)
        })

    return pd.DataFrame(contributions).sort_values('Contribution', ascending=False)