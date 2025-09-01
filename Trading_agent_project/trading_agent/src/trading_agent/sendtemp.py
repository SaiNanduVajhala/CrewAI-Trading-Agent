import os
import logging
import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send_message(self, text: str):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            #"parse_mode": "Markdown"
        }
        try:
            response = requests.post(url, data=payload, timeout=10)
            if response.status_code == 200:
                logger.info("Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram API error {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

def send_file(file_path: str, notifier: TelegramNotifier):
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if not content.strip():
        logger.warning("File content is empty")
        return False

    # Telegram message limit ~4096 chars; split if needed
    max_length = 4000
    success = True

    for start in range(0, len(content), max_length):
        chunk = content[start:start+max_length]
        if start + max_length < len(content):
            chunk += "\n\n(continued...)"

        if not notifier.send_message(chunk):
            success = False
            break

    return success

if __name__ == "__main__":
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    file_path = "04_translate.md"

    if not token or not chat_id:
        logger.error("Environment variables TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")
        exit(1)

    notifier = TelegramNotifier(token, chat_id)
    if send_file(file_path, notifier):
        logger.info(f"{file_path} sent successfully to Telegram channel")
    else:
        logger.error(f"Failed to send {file_path} to Telegram channel")
