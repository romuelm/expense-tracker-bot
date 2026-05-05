from google import genai
from config import GEMINI_API_KEY, TELEGRAM_TOKEN

import pandas as pd
import os
import json
import re

from datetime import datetime, timedelta
from dateutil import parser

from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# 🔹 Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# 🔹 Excel file
FILE = "expenses.xlsx"

# 🔹 Allowed categories
CATEGORIES = ["food", "transport", "bills", "shopping", "others"]


# 🔥 1. FIXED DATE PARSER (no amount confusion)
def resolve_date(text):
    text = text.lower()
    today = datetime.now()

    try:
        # 🔥 Remove standalone numbers (prevents 2500 → year bug)
        cleaned_text = re.sub(r"\b\d+\b", "", text)

        if "yesterday" in cleaned_text:
            return (today - timedelta(days=1)).strftime("%Y-%m-%d")

        match = re.search(r"(\d+)\s+days?\s+ago", text)
        if match:
            days = int(match.group(1))
            return (today - timedelta(days=days)).strftime("%Y-%m-%d")

        if "today" in cleaned_text:
            return today.strftime("%Y-%m-%d")

        # Only parse if month words exist
        if any(word in cleaned_text for word in [
            "jan","feb","mar","apr","may","jun",
            "jul","aug","sep","oct","nov","dec"
        ]):
            parsed = parser.parse(cleaned_text, fuzzy=True)
            return parsed.strftime("%Y-%m-%d")

        return today.strftime("%Y-%m-%d")

    except:
        return today.strftime("%Y-%m-%d")


# 🔹 2. Gemini parsing
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


# 🔹 3. Clean JSON
def clean_json(text):
    try:
        json_text = re.search(r"\{.*\}", text, re.DOTALL).group()
        return json.loads(json_text)
    except:
        return None


# 🔥 4. Standardize + validate
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
        elif any(x in name for x in ["grab", "ride", "taxi"]):
            category = "transport"
        elif any(x in name for x in ["rent", "electric", "bill"]):
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


# 🔹 5. Save to Excel
def save_to_excel(data):
    df_new = pd.DataFrame([data], columns=["category", "name", "amount", "date"])

    if os.path.exists(FILE):
        df = pd.read_excel(FILE)
        df = pd.concat([df, df_new], ignore_index=True)
    else:
        df = df_new

    df.to_excel(FILE, index=False)


# 🔹 6. Telegram handler
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    result = parse_expense(user_text)
    raw_data = clean_json(result)
    data = standardize_data(raw_data, user_text)

    if data:
        save_to_excel(data)

        reply = (
            f"✅ Saved\n"
            f"📌 {data['name']}\n"
            f"💰 ₱{data['amount']}\n"
            f"📂 {data['category']}\n"
            f"📅 {data['date']}"
        )
    else:
        reply = "❌ Please include at least a name and amount (e.g. coffee 120)"

    await update.message.reply_text(reply)


# 🔹 7. Run bot
if __name__ == "__main__":
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Bot running...")
    app.run_polling()