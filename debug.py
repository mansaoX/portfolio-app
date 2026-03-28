from supabase_client import supabase

result = supabase.table("transactions")\
    .select("*")\
    .eq("account_number", "10000")\
    .lte("date", "2026-03-28")\
    .execute()

print("Transactions found:", len(result.data))
for t in result.data:
    print(t)
