import os
import re
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from PIL import Image
import pytesseract
import pandas as pd

# CONFIGURATION
TOKEN = os.environ.get("TELEGRAM_TOKEN")

# Setup Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# In-memory storage
# New Structure: 
# { 
#   topic_id: {
#       'data': [{'number': '09123...', 'amount': 500.0}], 
#       'processed_ids': set('unique_id_1', 'unique_id_2')
#   } 
# }
data_store = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hello! I am ready to scan GCash receipts. I will also ignore duplicate photos!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Instructions:\n"
        "1. Send a GCash receipt photo here.\n"
        "2. I will read the Number and Amount.\n"
        "3. I will ignore duplicate images.\n"
        "4. Type /total to see the summary."
    )
    await update.message.reply_text(text)

def extract_receipt_data(image_path):
    """
    Uses OCR to find GCash Number and Amount in the image.
    """
    try:
        text = pytesseract.image_to_string(Image.open(image_path))
        clean_text = text.replace(',', '') 
        
        # Regex for Amount
        amount_match = re.search(r'(?:Amount|Sent)\D*(\d+\.\d{2})', clean_text, re.IGNORECASE)
        
        # Regex for PH Phone Number
        number_match = re.search(r'(\+63\s?9\d{2}[\s-]?\d{3}[\s-]?\d{4})|(09\d{2}[\s-]?\d{3}[\s-]?\d{4})', clean_text)

        amount = 0.0
        number = "Unknown"

        if amount_match:
            amount = float(amount_match.group(1))
        
        if number_match:
            number = number_match.group(0).replace(" ", "").replace("-", "")

        return number, amount
    except Exception as e:
        logging.error(f"OCR Error: {e}")
        return None, 0.0

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    # Initialize storage for this topic if not exists
    if topic_id not in data_store:
        data_store[topic_id] = {'data': [], 'processed_ids': set()}

    # Check for Duplicate Image
    photo_obj = update.message.photo[-1]
    unique_id = photo_obj.file_unique_id

    if unique_id in data_store[topic_id]['processed_ids']:
        await update.message.reply_text("⚠️ Duplicate receipt detected! Ignoring.", quote=True)
        return

    # Download and Process
    photo_file = await photo_obj.get_file()
    file_path = "temp_receipt.jpg"
    await photo_file.download_to_drive(file_path)

    number, amount = extract_receipt_data(file_path)

    if amount > 0:
        # Save Data
        data_store[topic_id]['data'].append({'number': number, 'amount': amount})
        # Mark Image as Processed
        data_store[topic_id]['processed_ids'].add(unique_id)
        
        await update.message.reply_text(f"✅ Recorded: {number} - ₱{amount:,.2f}", quote=True)
    else:
        await update.message.reply_text("⚠️ Couldn't read the amount clearly. Please type it manually if needed.", quote=True)

async def calculate_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    
    if topic_id not in data_store or not data_store[topic_id]['data']:
        await update.message.reply_text("No receipts found for this topic yet.")
        return

    df = pd.DataFrame(data_store[topic_id]['data'])
    
    summary = df.groupby('number')['amount'].sum().reset_index()
    total_overall = df['amount'].sum()

    report = "📊 **GCash Summary**\n\n"
    for index, row in summary.iterrows():
        report += f"👤 `{row['number']}`: ₱{row['amount']:,.2f}\n"
    
    report += f"\n**Total Collected:** ₱{total_overall:,.2f}"

    await update.message.reply_text(report, parse_mode='Markdown')

async def clear_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic_id = update.message.message_thread_id if update.message.message_thread_id else update.message.chat_id
    if topic_id in data_store:
        del data_store[topic_id]
        await update.message.reply_text("🗑️ Data for this topic has been cleared.")
    else:
        await update.message.reply_text("Nothing to clear.")

if __name__ == '__main__':
    if not TOKEN:
        print("Error: TELEGRAM_TOKEN not found in environment variables.")
        exit(1)
        
    application = ApplicationBuilder().token(TOKEN).build()

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('help', help_command))
    application.add_handler(CommandHandler('total', calculate_total))
    application.add_handler(CommandHandler('clear', clear_data))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    application.run_polling()
