import psycopg2
import sqlite3
from config import DATABASE_URL

# This is the name of the file that will be created on your PC
LOCAL_DB = "analytics_expenses.db"

def run_etl():
    try:
        # 1. Connect to Neon (Cloud)
        neon_conn = psycopg2.connect(DATABASE_URL)
        neon_cur = neon_conn.cursor()
        
        # 2. Connect to SQLite (Local)
        sqlite_conn = sqlite3.connect(LOCAL_DB)
        sqlite_cur = sqlite_conn.cursor()
        
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return

    try:
        # 3. Create Local Table if it's missing
        sqlite_cur.execute("""
            CREATE TABLE IF NOT EXISTS analytics_expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cloud_id INTEGER,
                category TEXT,
                name TEXT,
                amount REAL,
                date TEXT,
                inserted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        sqlite_conn.commit()

        # 4. Fetch New Rows from Neon
        neon_cur.execute("SELECT id, category, name, amount, date FROM transactions;")
        rows = neon_cur.fetchall()
        
        if not rows:
            print("📭 No new transactions to fetch from Neon.")
            return

        print(f"📥 Fetched {len(rows)} transactions from Neon.")

        # 5. Append Rows to Local SQLite (With Decimal & Date fixes!)
        for row in rows:
            # We convert amount to float, and wrap the date in str() to prevent warnings
            clean_row = (row[0], row[1], row[2], float(row[3]), str(row[4]))
            
            sqlite_cur.execute("""
                INSERT INTO analytics_expenses (cloud_id, category, name, amount, date)
                VALUES (?, ?, ?, ?, ?)
            """, clean_row)
            
        sqlite_conn.commit()
        print("💾 Successfully appended records to local SQLite database.")

        # 6. Purge the Neon Database Table
        ids_to_delete = tuple(row[0] for row in rows)
        
        if len(ids_to_delete) == 1:
            neon_cur.execute(f"DELETE FROM transactions WHERE id = {ids_to_delete[0]};")
        else:
            neon_cur.execute(f"DELETE FROM transactions WHERE id IN {ids_to_delete};")
            
        neon_conn.commit()
        print("🧼 Neon cloud database purged and reset.")

    except Exception as e:
        print(f"❌ ETL Pipeline Failed: {e}")
        sqlite_conn.rollback()
        neon_conn.rollback()
        
    finally:
        # 7. Close everything safely
        neon_cur.close()
        neon_conn.close()
        sqlite_cur.close()
        sqlite_conn.close()

if __name__ == "__main__":
    print("🚀 Starting local ETL sync...")
    run_etl()