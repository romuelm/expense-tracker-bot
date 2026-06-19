from google import genai
from dags.config import GEMINI_API_KEY, TELEGRAM_TOKEN, DATABASE_URL

# 1. Import necessary libraries
import psycopg2
import os
import json
import re

from datetime import datetime, timedelta
from dateutil import parser

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

#Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

#Allowed categories
CATEGORIES = ["food", "transport", "bills", "shopping", "others"]


#1. FIXED DATE PARSER
def resolve_date(text):
    text = text.lower()
    today = datetime.now()

    try:
        cleaned_text = re.sub(r"\b\d+\b", "", text)

        if "yesterday" in cleaned_text:
            return (today - timedelta(days=1)).strftime("%Y-%m-%d")

        match = re.search(r"(\d+)\s+days?\s+ago", text)
        if match:
            days = int(match.group(1))
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")

        if "today" in cleaned_text:
            return today.strftime("%Y-%m-%d")

        if any(word in cleaned_text for word in [
            "jan","feb","mar","apr","may","jun",
            "jul","aug","sep","oct","nov","dec"
        ]):
            parsed = parser.parse(cleaned_text, fuzzy=True)
            return parsed.strftime("%Y-%m-%d")

        return today.strftime("%Y-%m-%d")

    except:
        return today.strftime("%Y-%m-%d")


#2. Gemini parsing
def parse_expense(text):
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=f"""
        Extract expense data from this message:

        "{text}"

        Return ONLY JSON:
        {{
            "name": "string",
            "amount": number,
            "category": "optional"
        }}
        """
    )
    return response.text


#3. Clean JSON
def clean_json(text):
    try:
        json_text = re.search(r"\{.*\}", text, re.DOTALL).group()
        return json.loads(json_text)
    except:
        return None


#4. Standardize + validate
def standardize_data(data, user_text):
    if not data:
        return None

    if "name" not in data or "amount" not in data:
        return None

    name = str(data["name"]).lower()
    amount = float(data["amount"])
    category = str(data.get("category", "")).lower()

    if category not in CATEGORIES:
        if any(x in name for x in ["coffee", "jollibee", "food", "meal"]):
            category = "food"
        elif any(x in name for x in ["grab", "ride", "taxi", "bus", "jeep", "tricycle"]):
            category = "transport"
        elif any(x in name for x in ["rent", "electric", "bill", "gas", "load"]):
            category = "bills"
        else:
            category = "others"

    date = resolve_date(user_text)

    return {
        "category": category,
        "name": name,
        "amount": amount,
        "date": date
    }


#5. Save to Neon PostgreSQL
def save_to_db(data):
    try:
        # Establish connection to Neon
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()

        # Automatically create the transactions table if it's missing
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id SERIAL PRIMARY KEY,
                category VARCHAR(50),
                name VARCHAR(255),
                amount DECIMAL(10, 2),
                date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Insert entry
        cur.execute("""
            INSERT INTO transactions (category, name, amount, date)
            VALUES (%s, %s, %s, %s)
        """, (data['category'], data['name'], data['amount'], data['date']))

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database error: {e}")
        return False


#6. Telegram handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    result = parse_expense(user_text)
    raw_data = clean_json(result)
    data = standardize_data(raw_data, user_text)

    if data:
        db_success = save_to_db(data) # 🔥 Call the database insert function
        
        if db_success:
            reply = (
                f"✅ Saved to Database\n"
                f"📌 {data['name']}\n"
                f"💰 ₱{data['amount']}\n"
                f"📂 {data['category']}\n"
                f"📅 {data['date']}"
            )
        else:
            reply = "⚠️ Connected to bot, but failed to save to the database."
    else:
        reply = "❌ Please include at least a name and amount (e.g. coffee 120)"

    await update.message.reply_text(reply)


#7. Run bot
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running locally and connected to Neon PostgreSQL...")
    app.run_polling()