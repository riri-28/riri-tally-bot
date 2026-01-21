import os
import re
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from PIL import Image
import pytesseract
import pandas as pd

# --- Master Directory ---
# 1. GCash Names
# 2. CIMB Numbers
# 3. BDO Truncated Numbers
# 4. PayPal Keywords
NAME_DIRECTORY = {
    # GCASH
    "ROWELYN DELOS SANTOS": "09474275406",
    "ROWELYN": "09474275406",
    "IRAH GABALES AREVALO": "09702610852",
    "IRAH AREVALO": "09702610852",
    "IRAH GABALES": "09702610852",
    "ROSALYN BACATANO": "09777995750",
    "ROSALYN": "09777995750",
    "REGINE ZONIO": "09469386324",
    "REGINE": "09469386324",
    "RIEWEN JAY LLAIT": "09098730507",
    "RIEWEN": "09098730507",
    "PHILOMENA MICHAELA SANTOS": "09469407091",
    "PHILOMENA SANTOS": "09469407091",
    
    # CIMB (Full Numbers)
    "20860741297082": "20860741297082 (CIMB Rowelyn)",
    "20860804773914": "20860804773914 (CIMB Irah)",

    # BDO (Full + Truncated)
    "008810123749": "008810123749 (BDO Rowelyn)",
    "3749": "008810123749 (BDO Rowelyn)",

    # PAYPAL / KDV GAMING STORE
    # Detecting these words will map to the KDV Account
    "PAYPAL": "09474275406 (KDV/PayPal)",
    "KDV GAMING": "09474275406 (KDV/PayPal)",
    "KDV GAMING STORE": "09474275406 (KDV/PayPal)",
    "LEVELUPNF2024": "09474275406 (KDV/PayPal)"
}

# --- Fake Web Server ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Bot is alive!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
# -----------------------

# CONFIGURATION
TOKEN = os.environ.get("TELEGRAM_TOKEN")

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

data_store = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am ready to tally receipts (GCash, CIMB, BDO, PayPal).")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Instructions:\n"
        "1. Send receipt -> I count it.\n"
        "2. Reply '/scan' -> I count old photo.\n"
        "3. /total -> View summary.\n"
        "4. /directory -> View saved names."
    )
    await update.message.reply_text(text)

async def view_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📖 **Saved Directory:**\n\n"
    for name, number in NAME_DIRECTORY.items():
        msg += f"- {name}: `{number}`\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

def extract_receipt_data(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        clean_text = text.replace(',', '') 
        
        # 1. Search for Amount
        amount_match = re.search(r'(?:Amount|Sent|Total|Transfer|PHP)\D*(\d+\.\d{2})', clean_text, re.IGNORECASE)
        
        # 2. Search for Phone Number
        number_match = re.search(r'(\+63\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4})|(09\d{2}[\s-]?\d{3}[\s-]?\d{4})', clean_text)

        amount = 0.0
        number = "Unknown"

        if amount_match:
            amount = float(amount_match.group(1))
        
        if number_match:
            number = number_match.group(0).replace(" ", "").replace("-", "")
        else:
            # Check the Directory
            upper_text = clean_text.upper()
            found_match = False
            
            sorted_keys = sorted(NAME_DIRECTORY.keys(), key=len, reverse=True)
            
            for key_name in sorted_keys:
                if key_name in upper_text:
                    number = NAME_DIRECTORY[key_name]
                    found_match = True
                    break 
            
            if not found_match:
                if "3749" in upper_text:
                     number = "008810123749 (BDO Rowelyn)"

        return number, amount
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        return None, 0.0

async def process_photo_data(update, photo_obj):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    if topic_id not in data_store:
        data_store[topic_id] = {'data': [], 'processed_ids': set()}

    unique_id = photo_obj.file_unique_id

    if unique_id in data_store[topic_id]['processed_ids']:
        await update.message.reply_text("⚠️ Duplicate receipt detected!", quote=True)
        return

    photo_file = await photo_obj.get_file()
    file_path = "temp_receipt.jpg"
    await photo_file.download_to_drive(file_path)

    number, amount = extract_receipt_data(file_path)

    if amount > 0:
        if number == "Unknown":
             await update.message.reply_text(f"⚠️ I saw ₱{amount:,.2f} but couldn't find a Number or Name.", quote=True)
        else:
            data_store[topic_id]['data'].append({'number': number, 'amount': amount})
            data_store[topic_id]['processed_ids'].add(unique_id)
            await update.message.reply_text(f"✅ Recorded: {number} - ₱{amount:,.2f}", quote=True)
    else:
        await update.message.reply_text("⚠️ Couldn't read the amount.", quote=True)

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_photo_data(update, update.message.photo[-1])

async def manual_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("⚠️ Please reply to a photo.")
        return
    await process_photo_data(update, update.message.reply_to_message.photo[-1])

async def calculate_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    if topic_id not in data_store or not data_store[topic_id]['data']:
        await update.message.reply_text("No receipts found for this topic yet.")
        return

    df = pd.DataFrame(data_store[topic_id]['data'])
    summary = df.groupby('number')['amount'].sum().reset_index()
    total_overall = df['amount'].sum()

    report = "📊 **Summary Report**\n\n"
    for index, row in summary.iterrows():
        report += f"👤 `{row['number']}`: ₱{row['amount']:,.2f}\n"
    
    report += f"\n**Total:** ₱{total_overall:,.2f}"

    await update.message.reply_text(report, parse_mode='Markdown')

async def clear_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    if topic_id in data_store:
        del data_store[topic_id]
        await update.message.reply_text("🗑️ Topic data cleared.")
    else:
        await update.message.reply_text("Nothing to clear.")

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN not found.")
        exit(1)
    
    web_thread = threading.Thread(target=run_web_server)
    web_thread.daemon = True
    web_thread.start()

    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('total', calculate_total))
    application.add_handler(CommandHandler('clear', clear_data))
    application.add_handler(CommandHandler('scan', manual_scan_command))
    application.add_handler(CommandHandler('directory', view_directory))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    application.run_polling()
