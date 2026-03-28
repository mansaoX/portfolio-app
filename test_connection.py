from supabase_client import supabase

result = supabase.table("accounts").select("*").execute()
print("Connection works! Accounts table:", result.data)