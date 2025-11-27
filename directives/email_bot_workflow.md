# Telegram Email Bot Workflow

## Goal
Use a Telegram bot to draft and send emails to prospects listed in a Google Sheet, using context from a Google Doc.

## Inputs
- **Google Doc**: Contains company information and context.
- **Google Sheet**: Contains a list of prospects (Name, Email).
- **User Input**: Chat interaction via Telegram to refine the email.

## Tools
- `execution/telegram_bot.py`: The main bot entry point.
- `execution/services.py`: Handles API interactions (Google, OpenAI).

## Process
1.  **Start**: User sends `/start` to the bot.
2.  **Context Loading**: Bot reads the Google Doc to understand the company.
3.  **Drafting**:
    - Bot asks user what kind of email to send.
    - Bot asks OpenAI to generate a generic email draft (using placeholders like [Prospect Name]).
    - Bot sends the draft to the user on Telegram.
4.  **Refinement Loop**:
    - User can reply with feedback (e.g., "Make it shorter", "Add more enthusiasm").
    - Bot regenerates the draft and sends it back.
5.  **Confirmation**:
    - User clicks "Approve & Send to All".
6.  **Sending**:
    - Bot reads the Google Sheet to get the list of prospects.
    - Bot iterates through the list, replaces placeholders with prospect names, and sends emails via Gmail API.
    - Bot reports the number of emails sent.

## Edge Cases
- **API Errors**: If Google or OpenAI APIs fail, notify the user and retry.
- **Empty Sheet**: If no prospects are found, notify the user.
- **Rate Limits**: Handle Telegram or OpenAI rate limits gracefully.
