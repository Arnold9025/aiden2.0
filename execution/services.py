import os
import json
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import openai
import config
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# If modifying these scopes, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/documents.readonly',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/gmail.send'
]

class GoogleService:
    def __init__(self):
        self.creds = None
        
        # 1. Handle Client Secrets (credentials.json) from Env Var if file missing
        if not os.path.exists(config.GOOGLE_CREDENTIALS_FILE):
            creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
            if creds_json:
                with open(config.GOOGLE_CREDENTIALS_FILE, "w") as f:
                    f.write(creds_json)
        
        # 2. Try to load Token
        # Priority: Env Var (JSON) -> File (JSON) -> File (Pickle - Legacy)
        
        token_json = os.getenv("GOOGLE_TOKEN_JSON")
        if token_json:
            try:
                self.creds = Credentials.from_authorized_user_info(json.loads(token_json), SCOPES)
            except Exception as e:
                print(f"Error loading token from env: {e}")

        if not self.creds and os.path.exists(config.GOOGLE_TOKEN_FILE):
            try:
                self.creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, SCOPES)
            except Exception:
                # Fallback to pickle for backward compatibility
                try:
                    import pickle
                    with open(config.GOOGLE_TOKEN_FILE, 'rb') as token:
                        self.creds = pickle.load(token)
                except Exception as e:
                    print(f"Error loading token file: {e}")

        # 3. Refresh or Login
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                try:
                    self.creds.refresh(Request())
                except Exception as e:
                    print(f"Error refreshing token: {e}")
                    self.creds = None # Force re-login
            
            if not self.creds:
                # This will fail on server if no browser, but necessary for local setup
                flow = InstalledAppFlow.from_client_secrets_file(
                    config.GOOGLE_CREDENTIALS_FILE, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            # Save as JSON for future use (and easy copy-paste to env var)
            with open(config.GOOGLE_TOKEN_FILE, 'w') as token:
                token.write(self.creds.to_json())

        self.docs_service = build('docs', 'v1', credentials=self.creds)
        self.sheets_service = build('sheets', 'v4', credentials=self.creds)
        self.gmail_service = build('gmail', 'v1', credentials=self.creds)

    def read_doc(self, doc_id):
        try:
            document = self.docs_service.documents().get(documentId=doc_id).execute()
            content = ""
            for element in document.get('body').get('content'):
                if 'paragraph' in element:
                    elements = element.get('paragraph').get('elements')
                    for elem in elements:
                        if 'textRun' in elem:
                            content += elem.get('textRun').get('content')
            return content
        except HttpError as err:
            print(err)
            return None

    def read_sheet(self, sheet_id, range_name):
        try:
            sheet = self.sheets_service.spreadsheets()
            result = sheet.values().get(spreadsheetId=sheet_id, range=range_name).execute()
            values = result.get('values', [])
            return values
        except HttpError as err:
            print(err)
            return []

    def get_sheet_names(self, spreadsheet_id):
        try:
            sheet_metadata = self.sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheets = sheet_metadata.get('sheets', [])
            return [sheet.get("properties", {}).get("title", "Sheet1") for sheet in sheets]
        except HttpError as err:
            print(err)
            return []

    def send_email(self, to, subject, body_html):
        try:
            message = MIMEMultipart('alternative')
            message['to'] = to
            message['subject'] = subject
            
            # Create a plain text version by stripping tags (simple approximation)
            import re
            clean = re.compile('<.*?>')
            body_text = re.sub(clean, '', body_html)
            
            part1 = MIMEText(body_text, 'plain')
            part2 = MIMEText(body_html, 'html')
            
            message.attach(part1)
            message.attach(part2)
            
            raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
            message = {'raw': raw}
            self.gmail_service.users().messages().send(userId='me', body=message).execute()
            return True, None
        except HttpError as err:
            print(err)
            return False, str(err)

class OpenAIService:
    def __init__(self):
        openai.api_key = config.OPENAI_API_KEY

    def generate_email(self, context, prospect_info, feedback=None, image_url=None):
        prompt = f"Context about the company:\n{context}\n\n"
        prompt += f"Prospect Info: {prospect_info}\n\n"
        if feedback:
            prompt += f"Previous feedback from user: {feedback}\n\n"
        
        image_instruction = ""
        if image_url:
            image_instruction = f"- Include this image at the top of the email (header): <img src='{image_url}' alt='Header Image' style='width:100%; max-width:600px; height:auto; display:block; margin: 0 auto;' />"

        prompt += f"""
        Draft a premium, modern, newspaper-style email to this prospect.
        Use HTML and inline CSS.
        {image_instruction}
        - Use a clean, serif font (like Merriweather or Georgia) for headings to give a newspaper feel.
        - Use a sans-serif font (like Arial or Helvetica) for body text.
        - Use a subtle background color (like #f4f4f4) for the outer container and white for the content box.
        - Add a professional header and footer.
        - Make it responsive.
        - IMPORTANT: Return ONLY the raw HTML code. Do not include any conversational text like "Here is the email" or markdown formatting. Start directly with <!DOCTYPE html> or <html>.
        """

        try:
            response = openai.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "You are a helpful sales assistant and expert email designer. You output ONLY raw HTML."},
                    {"role": "user", "content": prompt}
                ]
            )
            content = response.choices[0].message.content.strip()
            
            # cleaning logic
            # 1. Strip markdown code blocks
            if "```html" in content:
                content = content.split("```html")[1]
            if "```" in content:
                content = content.split("```")[0]
            
            # 2. Find start of HTML if there is still conversational text
            start_index = content.find("<html")
            if start_index == -1:
                start_index = content.find("<!DOCTYPE")
            if start_index == -1:
                start_index = content.find("<div")
                
            if start_index != -1:
                content = content[start_index:]
                
            return content.strip()
        except Exception as e:
            print(e)
            return "Error generating email."
