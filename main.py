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
NAME_DIRECTORY = {
    # --- GCASH ---
    "ROWELYN DELOS SANTOS": "09474275406",
    "ROWELYN": "09474275406",
    "5406": "09474275406",

    "IRAH GABALES AREVALO": "09702610852",
    "IRAH AREVALO": "09702610852",
    "IRAH GABALES": "09702610852",
    "0852": "09702610852",

    "ROSALYN BACATANO": "09777995750",
    "ROSALYN": "09777995750",
    "5750": "09777995750",

    "REGINE ZONIO": "09469386324",
    "REGINE": "09469386324",
    "6324": "09469386324",

    "RIEWEN JAY LLAIT": "09098730507",
    "RIEWEN": "09098730507",
    "0507": "09098730507",

    "PHILOMENA MICHAELA SANTOS": "09469407091",
    "PHILOMENA SANTOS": "09469407091",
    "7091": "09469407091",
    
    # --- CIMB ---
    "20860741297082": "20860741297082 (CIMB Rowelyn)",
    "7082": "20860741297082 (CIMB Rowelyn)",

    "20860804773914": "20860804773914 (CIMB Irah)",
    "3914": "20860804773914 (CIMB Irah)",

    # --- BDO ---
    "008810123749": "008810123749 (BDO Rowelyn)",
    "3749": "008810123749 (BDO Rowelyn)",

    # --- PAYPAL / KDV ---
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
    await update.message.reply_text("Hello! I'm ready. Reply /undo to a specific message to delete just that one.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Instructions:\n"
        "1. Send receipt -> I count it.\n"
        "2. /undo -> Delete the LAST entry.\n"
        "3. Reply /undo -> Delete THAT specific entry.\n"
        "4. /manual Number Amount -> Add manually.\n"
        "5. /total -> View summary.\n"
        "6. /directory -> View saved names."
    )
    await update.message.reply_text(text)

async def view_directory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = "📖 **Saved Directory:**\n\n"
    shown_numbers = set()
    for name, number in NAME_DIRECTORY.items():
        if len(name) > 4 and number not in shown_numbers:
            msg += f"- {name}: `{number}`\n"
            shown_numbers.add(number)
    await update.message.reply_text(msg, parse_mode='Markdown')

# --- SMART UNDO COMMAND ---
async def undo_last(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    if topic_id not in data_store or not data_store[topic_id]['data']:
        await update.message.reply_text("⚠️ Nothing to undo.")
        return

    # Check if this is a Reply to a specific bot message
    if update.message.reply_to_message:
        target_msg_id = update.message.reply_to_message.message_id
        data_list = data_store[topic_id]['data']
        
        # Search for the transaction linked to this message ID
        found_index = -1
        for i, item in enumerate(data_list):
            if item.get('bot_msg_id') == target_msg_id:
                found_index = i
                break
        
        if found_index != -1:
            removed_item = data_list.pop(found_index)
            # Remove from processed_ids so it can be scanned again
            if 'id' in removed_item and removed_item['id'] in data_store[topic_id]['processed_ids']:
                data_store[topic_id]['processed_ids'].remove(removed_item['id'])
            
            await update.message.reply_text(f"✅ Targeted Undo Successful.\nRemoved: {removed_item['number']} - ₱{removed_item['amount']:,.2f}", quote=True)
        else:
            await update.message.reply_text("⚠️ I couldn't find a record linked to that message. It might have been cleared.", quote=True)
            
    else:
        # Standard Undo (Last Item)
        last_item = data_store[topic_id]['data'].pop()
        
        if 'id' in last_item and last_item['id'] in data_store[topic_id]['processed_ids']:
            data_store[topic_id]['processed_ids'].remove(last_item['id'])

        await update.message.reply_text(f"↩️ Undo Last Successful.\nRemoved: {last_item['number']} - ₱{last_item['amount']:,.2f}")

async def manual_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    try:
        if len(context.args) < 2:
            await update.message.reply_text("⚠️ Usage: `/manual Number Amount`", parse_mode='Markdown')
            return

        amount = float(context.args[-1]) 
        number = " ".join(context.args[:-1]) 
        
        upper_name = number.upper()
        if upper_name in NAME_DIRECTORY:
            number = NAME_DIRECTORY[upper_name]

        if topic_id not in data_store:
            data_store[topic_id] = {'data': [], 'processed_ids': set()}

        # Note: We don't have a bot_msg_id for manual adds, so they can only be removed via standard /undo
        data_store[topic_id]['data'].append({'number': number, 'amount': amount, 'id': 'manual', 'bot_msg_id': None})
        
        await update.message.reply_text(f"✅ Manually Added: {number} - ₱{amount:,.2f}")

    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
# --------------------------------

def extract_receipt_data(image_path):
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        clean_text = text.replace(',', '') 
        
        amount_match = re.search(r'(?:Amount|Sent|Total|Transfer|PHP)\D*(\d+\.\d{2})', clean_text, re.IGNORECASE)
        number_match = re.search(r'(\+63\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4})|(09\d{2}[\s-]?\d{3}[\s-]?\d{4})', clean_text)

        amount = 0.0
        number = "Unknown"

        if amount_match:
            amount = float(amount_match.group(1))
        
        if number_match:
            number = number_match.group(0).replace(" ", "").replace("-", "")
        else:
            upper_text = clean_text.upper()
            found_match = False
            sorted_keys = sorted(NAME_DIRECTORY.keys(), key=len, reverse=True)
            
            for key_name in sorted_keys:
                if key_name in upper_text:
                    number = NAME_DIRECTORY[key_name]
                    found_match = True
                    break 
            
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
             await update.message.reply_text(f"⚠️ I saw ₱{amount:,.2f} but couldn't find a Number or Name.\nType: `/manual Number {amount}` to fix it.", quote=True, parse_mode='Markdown')
        else:
            # Send the reply first
            sent_msg = await update.message.reply_text(f"✅ Recorded: {number} - ₱{amount:,.2f}", quote=True)
            
            # Save the DATA along with the BOT'S MESSAGE ID
            data_store[topic_id]['data'].append({
                'number': number, 
                'amount': amount, 
                'id': unique_id, 
                'bot_msg_id': sent_msg.message_id  # <--- Crucial for targeted undo
            })
            data_store[topic_id]['processed_ids'].add(unique_id)
            
    else:
        await update.message.reply_text("⚠️ Couldn't read the amount. Use /manual to add it.", quote=True)

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
    application.add_handler(CommandHandler('undo', undo_last))
    application.add_handler(CommandHandler('manual', manual_add))
    
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    application.run_polling()
