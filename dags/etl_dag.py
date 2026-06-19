import psycopg2
import sqlite3
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator

# Import from config (Ensure config.py is inside the dags folder)
from config import DATABASE_URL

# Save inside Docker's mapped dags folder so it syncs back to Windows
LOCAL_DB = "/opt/airflow/dags/analytics_expenses.db"

def execute_etl():
    try:
        neon_conn = psycopg2.connect(DATABASE_URL)
        neon_cur = neon_conn.cursor()
        
        sqlite_conn = sqlite3.connect(LOCAL_DB)
        sqlite_cur = sqlite_conn.cursor()
    except Exception as e:
        print(f"❌ Connection Error: {e}")
        return

    try:
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

        neon_cur.execute("SELECT id, category, name, amount, date FROM transactions;")
        rows = neon_cur.fetchall()
        
        if not rows:
            print("📭 No new transactions to fetch from Neon.")
            return

        print(f"📥 Fetched {len(rows)} transactions from Neon.")

        for row in rows:
            clean_row = (row[0], row[1], row[2], float(row[3]), str(row[4]))
            sqlite_cur.execute("""
                INSERT INTO analytics_expenses (cloud_id, category, name, amount, date)
                VALUES (?, ?, ?, ?, ?)
            """, clean_row)
            
        sqlite_conn.commit()
        print("💾 Successfully appended records to local SQLite database.")

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
        neon_cur.close()
        neon_conn.close()
        sqlite_cur.close()
        sqlite_conn.close()

# Define the Airflow DAG Configuration
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2026, 6, 18),
    'retries': 1,
    'retry_delay': timedelta(minutes=1),
}

# This runs the script automatically every day at midnight ('@daily')
with DAG(
    'expense_etl_pipeline',
    default_args=default_args,
    description='Extracts expenses from Neon and loads to local SQLite',
    schedule_interval='30 12 * * *',
    catchup=False
) as dag:

    etl_task = PythonOperator(
        task_id='run_neon_to_sqlite',
        python_callable=execute_etl,
    )