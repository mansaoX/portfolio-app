import streamlit as st

pg = st.navigation({
    "": [
        st.Page("pages/0_Detailed_View.py", title="Detailed View"),
        st.Page("pages/1_Performance.py", title="Performance"),
    ],
    "Inputs": [
        st.Page("pages/2_import_transactions.py", title="Import Transactions"),
        st.Page("pages/1_manual_transaction.py", title="Manual Transaction"),
        st.Page("pages/3_manage_accounts.py", title="Manage Accounts"),
        st.Page("pages/4_manual_prices.py", title="Manual Prices"),
    ]
}, position="sidebar")

pg.run()