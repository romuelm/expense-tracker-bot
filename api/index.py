from google import genai
import psycopg2
import os
import json
import re
from datetime import datetime, timedelta
from dateutil import parser

# 🔥 NEW: Import FastAPI
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# Load configuration from environment variables (Required for Vercel)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Allowed categories
CATEGORIES = ["food", "transport", "bills", "shopping", "others"]

# 🔥 NEW: Initialize FastAPI app
app = FastAPI()

# 1. FIXED DATE PARSER
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
        if any(word in cleaned_text for word in ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"]):
            parsed = parser.parse(cleaned_text, fuzzy=True)
            return parsed.strftime("%Y-%m-%d")
        return today.strftime("%Y-%m-%d")
    except:
        return today.strftime("%Y-%m-%d")

# 2. Gemini parsing
def parse_expense(text):
    response = client.models.generate_content(
        model="gemini-3.1-flash-lite-preview",
        contents=f"""
        Extract expense data from this message:
        "{text}"
        
        Categorize the expense into EXACTLY ONE of these categories: food, transport, bills, shopping, others.
        If the user explicitly states a category in their message, prioritize using that category.
        
        Return ONLY JSON:
        {{
            "name": "string",
            "amount": number,
            "category": "string"
        }}
        """
    )
    return response.text

# 3. Clean JSON
def clean_json(text):
    try:
        json_text = re.search(r"\{.*\}", text, re.DOTALL).group()
        return json.loads(json_text)
    except:
        return None

# 4. Standardize + validate
def standardize_data(data, user_text):
    if not data:
        return None
    if "name" not in data or "amount" not in data:
        return None
    name = str(data["name"]).lower()
    amount = float(data["amount"])
    category = str(data.get("category", "")).lower()

    # Fallback if Gemini hallucinates a category outside your list
    if category not in CATEGORIES:
        category = "others"
        
    date = resolve_date(user_text)
    return {"category": category, "name": name, "amount": amount, "date": date}

# 5. Save to Neon PostgreSQL
def save_to_db(data):
    try:
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
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

# 6. Telegram handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    result = parse_expense(user_text)
    raw_data = clean_json(result)
    data = standardize_data(raw_data, user_text)

    if data:
        db_success = save_to_db(data) 
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

# 🔥 NEW: Section 7 - Webhook and App Setup for Vercel
# Initialize python-telegram-bot application globally
telegram_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

@app.on_event("startup")
async def startup_event():
    # Initialize the telegram app when the FastAPI server starts
    await telegram_app.initialize()

@app.post("/api/index")
async def webhook(request: Request):
    # This route receives the JSON payload from Telegram when a message is sent
    data = await request.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "Telegram bot is running on Vercel!"}