# Google Cloud Credentials Setup Guide

To run this bot, you need a `credentials.json` file from Google Cloud Platform.

## Steps

1.  **Go to Google Cloud Console**: [https://console.cloud.google.com/](https://console.cloud.google.com/)
2.  **Create a New Project**:
    - Click the project dropdown at the top.
    - Click "New Project".
    - Name it (e.g., "Email Bot") and create it.
3.  **Enable APIs**:
    - Go to **APIs & Services > Library**.
    - Search for and enable the following APIs:
        - **Google Docs API**
        - **Google Sheets API**
        - **Gmail API**
4.  **Configure OAuth Consent Screen**:
    - Go to **APIs & Services > OAuth consent screen**.
    - Choose **External** (unless you have a G Suite organization, then Internal is easier).
    - Fill in required fields (App name, support email).
    - Add your email as a **Test User**.
5.  **Create Credentials**:
    - Go to **APIs & Services > Credentials**.
    - Click **Create Credentials > OAuth client ID**.
    - Application type: **Desktop app**.
    - Name: "Desktop Client".
    - Click **Create**.
6.  **Download JSON**:
    - You will see a "Client ID created" modal.
    - Click the **Download JSON** button.
    - Save the file as `credentials.json` in the root of your project folder: `/Users/arnoldadadjisso/Desktop/Aiden_2.0/credentials.json`.

## After Adding the File
Once the file is in place, run the bot again:
```bash
python execution/telegram_bot.py
```
It will open a browser window to authenticate you.
