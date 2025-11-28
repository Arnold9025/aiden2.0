import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters, CallbackQueryHandler, ConversationHandler
import config
from services import GoogleService, OpenAIService

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

WAITING_FOR_SHEET_SELECTION = 1
WAITING_FOR_COLUMN_SELECTION = 2
WAITING_FOR_PROMPT = 3
WAITING_FOR_IMAGE = 4
WAITING_FOR_FEEDBACK = 5

class EmailBot:
    def __init__(self):
        self.google_service = GoogleService()
        self.openai_service = OpenAIService()
        self.context_doc = ""
        self.prospects = []
        self.current_prospect_index = 0
        self.current_draft = ""
        self.user_prompt = ""
        self.image_url = None
        self.selected_sheet = None
        self.selected_columns = []
        self.available_headers = []

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Hello! I'm ready to help you send emails.\n\nFirst, I'll read the context from your Google Doc...")
        
        # Load context only
        self.context_doc = self.google_service.read_doc(config.GOOGLE_DOC_ID)
        if not self.context_doc:
            await update.message.reply_text("Warning: Could not read Google Doc. Proceeding without context.")
        else:
            await update.message.reply_text("Context loaded.")

        # Get sheet names
        sheet_names = self.google_service.get_sheet_names(config.GOOGLE_SHEET_ID)
        
        if not sheet_names:
            await update.message.reply_text("Error: Could not list sheets. Please check your configuration.")
            return ConversationHandler.END
        
        # Create buttons for each sheet
        keyboard = []
        for name in sheet_names:
            keyboard.append([InlineKeyboardButton(name, callback_data=f"sheet|{name}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Please select the sheet containing your prospects:", reply_markup=reply_markup)
        return WAITING_FOR_SHEET_SELECTION

    async def handle_prompt(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        self.user_prompt = update.message.text
        await update.message.reply_text("Do you want to insert an image? (Reply with the Image URL or type 'no')")
        return WAITING_FOR_IMAGE

    async def handle_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text
        if text.lower() == 'no':
            self.image_url = None
        else:
            self.image_url = text
        
        await self.generate_and_preview(update, context)
        return WAITING_FOR_FEEDBACK

    async def handle_feedback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        feedback = update.message.text
        await update.message.reply_text("Regenerating based on feedback...")
        
        # Regenerate using prompt + feedback
        # We append feedback to the original prompt effectively
        self.user_prompt += f"\n\nFeedback: {feedback}"
        await self.generate_and_preview(update, context)
        return WAITING_FOR_FEEDBACK

    async def generate_and_preview(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        import re
        clean = re.compile('<.*?>')
        
        await update.message.reply_text("Drafting email...")
        dummy_prospect = {"name": "[Prospect Name]", "email": "[Prospect Email]"}
        
        self.current_draft = self.openai_service.generate_email(
            self.context_doc, 
            dummy_prospect, 
            self.user_prompt,
            image_url=self.image_url,
            available_columns=self.selected_columns
        )
        
        # Create text preview
        preview_text = re.sub(clean, '', self.current_draft)
        preview_text = re.sub(r'\n\s*\n', '\n\n', preview_text).strip()
        
        # Save HTML to file and send
        with open("draft_preview.html", "w", encoding="utf-8") as f:
            f.write(self.current_draft)
        
        await update.message.reply_document(document=open("draft_preview.html", "rb"), filename="draft.html", caption="Here is the HTML draft.")
        
        keyboard = [
            [InlineKeyboardButton("Approve & Send to All", callback_data='approve')],
            [InlineKeyboardButton("Refine", callback_data='refine')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"--- DRAFT PREVIEW (Text only) ---\n\n{preview_text}\n\n------------\n\nIf this looks good, click 'Approve & Send to All'.\nOtherwise, type your feedback to refine it.", reply_markup=reply_markup)



    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        if query.data == 'approve':
            await query.edit_message_text(text="Approved! Sending emails...")
            await self.process_sending(update, context)
            return ConversationHandler.END
            
        elif query.data == 'refine':
            await query.edit_message_text(text="Okay, please type your feedback.")
            return WAITING_FOR_FEEDBACK

    async def handle_sheet_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        if data.startswith("sheet|"):
            self.selected_sheet = data.split("|")[1]
            
            # Fetch headers
            self.available_headers = self.google_service.get_sheet_headers(config.GOOGLE_SHEET_ID, self.selected_sheet)
            
            if not self.available_headers:
                await query.edit_message_text(text=f"Selected '{self.selected_sheet}', but found no headers (first row is empty).")
                return ConversationHandler.END
                
            self.selected_columns = [] # Reset selection
            await self.show_column_selection(query, context)
            return WAITING_FOR_COLUMN_SELECTION

    async def show_column_selection(self, query, context):
        keyboard = []
        # Add buttons for each header
        for header in self.available_headers:
            # Mark selected columns
            label = f"✅ {header}" if header in self.selected_columns else header
            keyboard.append([InlineKeyboardButton(label, callback_data=f"col|{header}")])
        
        # Add Done button
        keyboard.append([InlineKeyboardButton("Done Selecting", callback_data="done_cols")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        msg_text = f"Sheet: {self.selected_sheet}\n\nPlease select the columns you want to use for personalization (e.g., Name, Company, Email).\nClick a column to toggle it."
        
        # If we are updating an existing message
        try:
            await query.edit_message_text(text=msg_text, reply_markup=reply_markup)
        except Exception:
            # Fallback if message content hasn't changed but markup has, or other issues
            await query.message.reply_text(text=msg_text, reply_markup=reply_markup)

    async def handle_column_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        data = query.data
        
        if data == "done_cols":
            if not self.selected_columns:
                await query.answer("Please select at least one column!", show_alert=True)
                return WAITING_FOR_COLUMN_SELECTION
            
            cols_str = ", ".join(self.selected_columns)
            await query.edit_message_text(text=f"Selected columns: {cols_str}\n\nNow, please tell me what kind of email you want to send to your prospects.")
            return WAITING_FOR_PROMPT
            
        if data.startswith("col|"):
            col_name = data.split("|")[1]
            if col_name in self.selected_columns:
                self.selected_columns.remove(col_name)
            else:
                self.selected_columns.append(col_name)
            
            await self.show_column_selection(query, context)
            return WAITING_FOR_COLUMN_SELECTION

    async def process_sending(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sheet_name = self.selected_sheet
        # Read Sheet (A:Z) - assuming max 26 columns for now, or just read all
        range_name = f"{sheet_name}!A:Z"
        all_rows = self.google_service.read_sheet(config.GOOGLE_SHEET_ID, range_name)
        
        chat_id = update.effective_chat.id
        
        if not all_rows:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: Could not read data from '{sheet_name}'.")
            return
        
        headers = all_rows[0]
        # Map header name to index
        header_map = {h.strip(): i for i, h in enumerate(headers)}
        
        # Find email column index
        email_col_index = -1
        for col in self.selected_columns:
            if "email" in col.lower():
                email_col_index = header_map.get(col)
                break
        
        # Fallback: look for 'email' in any header if not explicitly selected (though it should be)
        if email_col_index == -1:
             for h, i in header_map.items():
                 if "email" in h.lower():
                     email_col_index = i
                     break
        
        if email_col_index == -1:
            await context.bot.send_message(chat_id=chat_id, text="Error: Could not identify an 'Email' column. Please make sure one of the columns is named 'Email'.")
            return

        self.prospects = []
        skipped_count = 0
        
        # Start from row 1 (skip headers)
        for row in all_rows[1:]:
            if not row: continue
            
            # Get email
            if len(row) > email_col_index:
                email = row[email_col_index].strip()
                if "@" not in email:
                    skipped_count += 1
                    continue
                
                # Build prospect dict for replacements
                prospect_data = {"email": email}
                for col_name in self.selected_columns:
                    idx = header_map.get(col_name)
                    if idx is not None and len(row) > idx:
                        prospect_data[col_name] = row[idx].strip()
                    else:
                        prospect_data[col_name] = "" # Empty if missing
                
                self.prospects.append(prospect_data)
            else:
                skipped_count += 1
        
        if not self.prospects:
            await context.bot.send_message(chat_id=chat_id, text="Error: No valid prospects found.")
            return
        
        await context.bot.send_message(chat_id=chat_id, text=f"Found {len(self.prospects)} prospects. Sending emails...")
        
        count = 0
        for prospect in self.prospects:
            # Personalize the email
            final_email = self.current_draft
            for col_name, value in prospect.items():
                # Replace [Column Name] with value
                # Case insensitive replacement would be better but let's stick to exact match for now based on selection
                final_email = final_email.replace(f"[{col_name}]", value)
            
            # Also try standard [Prospect Name] if 'Name' or 'Nom' was selected
            # This is a fallback/helper if the prompt used generic placeholders
            
            success, error_msg = self.google_service.send_email(prospect['email'], "Information", final_email)
            if success:
                count += 1
            else:
                await context.bot.send_message(chat_id=chat_id, text=f"Failed to send to {prospect['email']}: {error_msg}")
        
        await context.bot.send_message(chat_id=chat_id, text=f"Done! Sent {count} emails.")

    async def debug_bot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        status_msg = "--- DEBUG STATUS ---\n"
        
        # Check OpenAI
        import config
        if config.OPENAI_API_KEY:
            status_msg += "✅ OpenAI API Key found.\n"
        else:
            status_msg += "❌ OpenAI API Key MISSING.\n"
            
        # Check Google Credentials
        import os
        if os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
             status_msg += "✅ credentials.json found.\n"
        else:
             status_msg += "❌ credentials.json MISSING.\n"
             
        if os.path.exists(config.GOOGLE_TOKEN_FILE):
             status_msg += "✅ token.json found.\n"
        else:
             status_msg += "❌ token.json MISSING.\n"
             
        # Check Google Service Creds
        if self.google_service.creds and self.google_service.creds.valid:
            status_msg += "✅ Google Credentials valid.\n"
        else:
            status_msg += "❌ Google Credentials invalid or not loaded.\n"
            
        await update.message.reply_text(status_msg)

if __name__ == '__main__':
    bot = EmailBot()
    application = ApplicationBuilder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', bot.start)],
        states={
            WAITING_FOR_SHEET_SELECTION: [CallbackQueryHandler(bot.handle_sheet_selection)],
            WAITING_FOR_COLUMN_SELECTION: [CallbackQueryHandler(bot.handle_column_selection)],
            WAITING_FOR_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_prompt)],
            WAITING_FOR_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_image)],
            WAITING_FOR_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_feedback),
                CallbackQueryHandler(bot.button_handler)
            ]
        },
        fallbacks=[CommandHandler('start', bot.start)]
    )
    
    application.add_handler(CommandHandler('debug', bot.debug_bot))
    application.add_handler(conv_handler)
    application.run_polling()
