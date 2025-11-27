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

WAITING_FOR_PROMPT = 1
WAITING_FOR_IMAGE = 2
WAITING_FOR_FEEDBACK = 3
WAITING_FOR_SHEET_NAME = 4

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

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("Hello! I'm ready to help you send emails.\n\nFirst, I'll read the context from your Google Doc...")
        
        # Load context only
        self.context_doc = self.google_service.read_doc(config.GOOGLE_DOC_ID)
        if not self.context_doc:
            await update.message.reply_text("Warning: Could not read Google Doc. Proceeding without context.")
        else:
            await update.message.reply_text("Context loaded.")

        await update.message.reply_text("Please tell me what kind of email you want to send to your prospects.")
        return WAITING_FOR_PROMPT

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
            image_url=self.image_url
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
            # Get sheet names
            sheet_names = self.google_service.get_sheet_names(config.GOOGLE_SHEET_ID)
            
            if not sheet_names:
                await query.edit_message_text(text="Approved! But I couldn't list the sheets. Please reply with the exact sheet name manually.")
            else:
                # Create buttons for each sheet
                keyboard = []
                for name in sheet_names:
                    # Use a prefix to identify sheet selection
                    keyboard.append([InlineKeyboardButton(name, callback_data=f"sheet|{name}")])
                
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(text="Approved! Please select the sheet to use:", reply_markup=reply_markup)
            
            return WAITING_FOR_SHEET_NAME
            
        elif query.data == 'refine':
            await query.edit_message_text(text="Okay, please type your feedback.")
            return WAITING_FOR_FEEDBACK

    async def handle_sheet_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        
        data = query.data
        if data.startswith("sheet|"):
            sheet_name = data.split("|")[1]
            await query.edit_message_text(text=f"Selected '{sheet_name}'. Reading prospects...")
            await self.process_sheet_processing(update, context, sheet_name)
            return ConversationHandler.END

    async def handle_sheet_name(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        sheet_name = update.message.text.strip()
        await update.message.reply_text(f"Reading prospects from '{sheet_name}'...")
        await self.process_sheet_processing(update, context, sheet_name)
        return ConversationHandler.END

    async def process_sheet_processing(self, update: Update, context: ContextTypes.DEFAULT_TYPE, sheet_name: str):
        # Read Sheet (A:C)
        range_name = f"{sheet_name}!A:C"
        all_rows = self.google_service.read_sheet(config.GOOGLE_SHEET_ID, range_name)
        
        # Determine chat_id based on update type (message or callback)
        chat_id = update.effective_chat.id
        
        if not all_rows:
            await context.bot.send_message(chat_id=chat_id, text=f"Error: Could not read data from '{sheet_name}'. Please check the name and try again.")
            return
        
        self.prospects = []
        skipped_count = 0
        for row in all_rows:
            # We expect at least 3 columns: Nom, Prenom, Email
            if len(row) >= 3:
                last_name = row[0].strip()
                first_name = row[1].strip()
                email = row[2].strip()
                
                if "@" not in email:
                    skipped_count += 1
                    continue
                    
                full_name = f"{first_name} {last_name}"
                self.prospects.append({"name": full_name, "email": email})
            else:
                skipped_count += 1
        
        if skipped_count > 0:
                await context.bot.send_message(chat_id=chat_id, text=f"Skipped {skipped_count} rows with invalid emails (likely headers).")
        
        if not self.prospects:
            await context.bot.send_message(chat_id=chat_id, text="Error: No valid prospects found in the sheet.")
            return
        
        await context.bot.send_message(chat_id=chat_id, text=f"Found {len(self.prospects)} prospects. Sending emails...")
        
        count = 0
        for prospect in self.prospects:
            # Personalize the email
            final_email = self.current_draft.replace("[Prospect Name]", prospect['name'])
            
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
            WAITING_FOR_PROMPT: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_prompt)],
            WAITING_FOR_IMAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_image)],
            WAITING_FOR_FEEDBACK: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_feedback),
                CallbackQueryHandler(bot.button_handler)
            ],
            WAITING_FOR_SHEET_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_sheet_name),
                CallbackQueryHandler(bot.handle_sheet_selection)
            ]
        },
        fallbacks=[CommandHandler('start', bot.start)]
    )
    
    application.add_handler(CommandHandler('debug', bot.debug_bot))
    application.add_handler(conv_handler)
    application.run_polling()
