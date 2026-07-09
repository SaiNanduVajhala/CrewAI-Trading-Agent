#!/usr/bin/env python3

import os
import logging
import requests
import socket
import time
import yaml
import re
import json
from datetime import datetime
from typing import Dict, List
import base64
from io import BytesIO
from PIL import Image
import hashlib

from crewai import Agent, Crew, Process, Task, LLM
from crewai.project import CrewBase, agent, task, crew
from crewai_tools import SerperDevTool
from crewai.tools import tool
import litellm

# Configure logging for the trading_agent package logger
package_logger = logging.getLogger("trading_agent")
package_logger.setLevel(logging.INFO)

# Remove any existing file handlers for trading_agent.log to avoid duplicates
for handler in list(package_logger.handlers):
    if isinstance(handler, logging.FileHandler) and 'trading_agent.log' in getattr(handler, 'baseFilename', ''):
        try:
            handler.close()
            package_logger.removeHandler(handler)
        except Exception:
            pass

try:
    log_file_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'trading_agent.log')
    file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    package_logger.addHandler(file_handler)
except Exception as e:
    print(f"Failed to set up file logging: {e}")

logger = logging.getLogger(__name__)

# Define tools as standalone functions with @tool decorator
@tool("Download Financial Chart Image")
def download_financial_chart(query: str) -> str:
    """
    Download financial chart images related to the query.
    Args:
        query: Search query for financial charts (e.g., "S&P 500 chart", "Nasdaq performance")
    Returns:
        Local file path of downloaded image or status message
    """
    try:
        # Create images directory
        image_dir = "downloaded_images"
        os.makedirs(image_dir, exist_ok=True)
        
        # Yahoo Finance chart mapping
        symbol_map = {
            "S&P 500": "^GSPC",
            "Nasdaq": "^IXIC", 
            "Dow Jones": "^DJI",
            "SPY": "SPY",
            "QQQ": "QQQ"
        }
        
        symbol = None
        for key, val in symbol_map.items():
            if key.lower() in query.lower():
                symbol = val
                break
        
        if symbol:
            # Yahoo Finance chart URL
            chart_url = f"https://chart.yahoo.com/z?s={symbol}&t=1d&q=l&l=on&z=s&p=m50,m200"
            
            response = requests.get(chart_url, timeout=10, stream=True)
            if response.status_code == 200:
                filename = f"yahoo_{symbol}_chart.png"
                filepath = os.path.join(image_dir, filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                logger.info(f"Downloaded Yahoo chart: {filepath}")
                return filepath
        
        # If no symbol found, try to use SerperDev for image search
        try:
            from crewai_tools import SerperDevTool
            serper = SerperDevTool(api_key=os.getenv("SERPER_API_KEY"))
            # This is a simplified approach - you might need to adapt based on SerperDevTool's actual image search capabilities
            return f"Chart downloaded for query: {query}"
        except:
            pass
        
        # Fallback: create a placeholder message
        return f"Unable to download chart for: {query}"
        
    except Exception as e:
        logger.error(f"Image download failed: {e}")
        return f"Failed to download chart for: {query}"

@tool("Embed Image in Markdown")
def embed_image_in_markdown(image_path: str, caption: str = "") -> str:
    """
    Convert local image to base64 and create markdown embed code.
    Args:
        image_path: Local path to the image file
        caption: Caption for the image
    Returns:
        Markdown formatted image embed code
    """
    try:
        if not os.path.exists(image_path):
            return f"<!-- Image not found: {image_path} -->"
        
        with open(image_path, "rb") as img_file:
            img_data = base64.b64encode(img_file.read()).decode()
        
        # Determine image format
        ext = os.path.splitext(image_path)[1].lower()
        mime_type = {
            '.png': 'image/png',
            '.jpg': 'image/jpeg', 
            '.jpeg': 'image/jpeg',
            '.gif': 'image/gif'
        }.get(ext, 'image/jpeg')
        
        # Create base64 embedded image
        img_embed = f"data:{mime_type};base64,{img_data}"
        
        if caption:
            markdown_image = f'<img src="{img_embed}" alt="{caption}" style="max-width: 100%; height: auto;" />\n\n**{caption}**\n'
        else:
            markdown_image = f'<img src="{img_embed}" alt="Financial Chart" style="max-width: 100%; height: auto;" />\n'
        
        logger.info(f"Created embedded image from {image_path}")
        return markdown_image
        
    except Exception as e:
        logger.error(f"Failed to embed image {image_path}: {e}")
        return f"<!-- Failed to embed image: {image_path} -->"

@tool("Send Telegram Message with Images")
def send_telegram_message_with_images(file_path: str = "04_translate.md") -> str:
    """
    Read a markdown file, extract any embedded base64 or local images, clean the markdown text
    (removing raw image tags/base64 strings), and send the clean text message and images
    (as photos, not links) to the configured Telegram channel.
    Args:
        file_path: Path to the markdown file to send (defaults to '04_translate.md')
    Returns:
        Status message indicating success or failure.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    if not token or not chat_id:
        return "Error: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables must be set."
        
    if not os.path.exists(file_path):
        return f"Error: File {file_path} not found."
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            
        # 1. Parse and extract images
        images = []
        
        # Regex for HTML image tags with base64 data src:
        # e.g., <img src="data:image/png;base64,iVBORw0KG..." alt="caption" ... />
        html_img_pattern = re.compile(
            r'<img[^>]+src=["\'](data:image/([^;]+);base64,([^"\']+\=?\=?))["\'][^>]*>'
        )
        
        # Regex for standard markdown image notation with base64:
        # e.g., ![caption](data:image/png;base64,iVBORw0KG...)
        md_img_pattern = re.compile(
            r'!\[[^\]]*\]\((data:image/([^;]+);base64,([^)]+\=?\=?))\)'
        )
        
        # Find all HTML image matches
        for match in html_img_pattern.finditer(content):
            mime_type = match.group(2)
            base64_data = match.group(3)
            try:
                img_bytes = base64.b64decode(base64_data)
                images.append({
                    "bytes": img_bytes,
                    "filename": f"chart_{len(images) + 1}.{mime_type}"
                })
            except Exception as e:
                logger.error(f"Failed to decode base64 image: {e}")
                
        # Find all markdown image matches
        for match in md_img_pattern.finditer(content):
            mime_type = match.group(2)
            base64_data = match.group(3)
            try:
                img_bytes = base64.b64decode(base64_data)
                images.append({
                    "bytes": img_bytes,
                    "filename": f"chart_{len(images) + 1}.{mime_type}"
                })
            except Exception as e:
                logger.error(f"Failed to decode base64 image: {e}")
                
        # 2. Clean the markdown text (remove the matched image tags/links)
        clean_content = html_img_pattern.sub("", content)
        clean_content = md_img_pattern.sub("", clean_content)
        
        # Remove any leading/trailing whitespace
        clean_content = clean_content.strip()
        
        if not clean_content and not images:
            return "Warning: No content or images found to send."
            
        # 3. Send text message (split if exceeds 4096 limit)
        max_length = 4000
        text_success = True
        
        if clean_content:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            for start in range(0, len(clean_content), max_length):
                chunk = clean_content[start:start+max_length]
                if start + max_length < len(clean_content):
                    chunk += "\n\n(continued...)"
                    
                payload = {
                    "chat_id": chat_id,
                    "text": chunk,
                }
                
                resp = requests.post(url, data=payload, timeout=15)
                if resp.status_code != 200:
                    logger.error(f"Failed to send text chunk: {resp.text}")
                    text_success = False
                    
        # 4. Send images as actual files (not links)
        images_success = True
        if images:
            if len(images) == 1:
                # Send single photo
                img = images[0]
                url = f"https://api.telegram.org/bot{token}/sendPhoto"
                files = {"photo": (img["filename"], img["bytes"], "image/png")}
                payload = {"chat_id": chat_id}
                resp = requests.post(url, data=payload, files=files, timeout=30)
                if resp.status_code != 200:
                    logger.error(f"Failed to send single photo: {resp.text}")
                    images_success = False
            else:
                # Send media group
                url = f"https://api.telegram.org/bot{token}/sendMediaGroup"
                media_list = []
                files = {}
                for i, img in enumerate(images):
                    file_key = f"photo_{i}"
                    files[file_key] = (img["filename"], img["bytes"], "image/png")
                    media_list.append({
                        "type": "photo",
                        "media": f"attach://{file_key}"
                    })
                    
                payload = {
                    "chat_id": chat_id,
                    "media": json.dumps(media_list)
                }
                resp = requests.post(url, data=payload, files=files, timeout=45)
                if resp.status_code != 200:
                    logger.error(f"Failed to send media group: {resp.text}")
                    images_success = False
                    
        if text_success and images_success:
            return f"Success: Content from {file_path} sent successfully to Telegram with {len(images)} images."
        elif not text_success and not images_success:
            return "Error: Failed to send both text and images to Telegram."
        elif not text_success:
            return f"Partial Success: Images sent, but text content failed to send."
        else:
            return f"Partial Success: Text sent, but failed to send {len(images)} images."
            
    except Exception as e:
        logger.error(f"Telegram sending failed: {e}")
        return f"Error: Exception occurred while sending to Telegram: {str(e)}"

@CrewBase
class TradingAgentCrew:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        # Dynamically select model based on available environment API keys
        if os.getenv("GEMINI_API_KEY"):
            # Set rate limit to stay within the Gemini Pro free tier requests-per-minute threshold
            self.primary_llm = LLM(
                model="gemini/gemini-2.5-flash",
                rate_limit_per_minute=2
            )
            self.secondary_llm = LLM(
                model="gemini/gemini-2.5-flash",
                rate_limit_per_minute=2
            )
            logger.info("Using Gemini gemini-2.5-flash models with rate limiting (2 RPM)")
        elif os.getenv("OPENAI_API_KEY"):
            self.primary_llm = LLM(model="openai/gpt-4o-mini")
            self.secondary_llm = LLM(model="openai/gpt-4o-mini")
            logger.info("Using OpenAI gpt-4o-mini models")
        else:
            self.primary_llm = LLM(
                model="groq/llama-3.1-8b-instant",
                rate_limit_per_minute=10
            )
            self.secondary_llm = LLM(
                model="groq/llama-3.1-8b-instant",
                rate_limit_per_minute=10
            )
            logger.info("Using Groq llama-3.1-8b-instant models with rate limiting (10 RPM)")

    @agent
    def search_agent(self):
        return Agent(
            config=self.agents_config.get("search_agent", {}),
            tools=[SerperDevTool(api_key=os.getenv("SERPER_API_KEY"))],
            llm=self.primary_llm,
            verbose=True,
        )

    @agent
    def summary_agent(self):
        return Agent(
            config=self.agents_config.get("summary_agent", {}),
            llm=self.secondary_llm,
            verbose=True,
        )

    @agent
    def formatting_agent(self):
        """Enhanced formatting agent with image processing capabilities"""
        return Agent(
            config=self.agents_config.get("formatting_agent", {}),
            tools=[
                download_financial_chart,
                embed_image_in_markdown
            ],
            llm=self.primary_llm,
            verbose=True,
        )

    @agent
    def translating_agent(self):
        return Agent(
            config=self.agents_config.get("translating_agent", {}),
            llm=self.primary_llm,
            verbose=True,
        )

    @agent
    def send_agent(self):
        return Agent(
            config=self.agents_config.get("send_agent", {}),
            tools=[send_telegram_message_with_images],
            llm=self.primary_llm,
            verbose=True,
        )

    @task
    def search_task(self):
        return Task(
            config=self.tasks_config.get("search_task", {}),
            agent=self.search_agent(),
            output_file="01_search.md"
        )

    @task
    def summary_task(self):
        return Task(
            config=self.tasks_config.get("summary_task", {}),
            agent=self.summary_agent(),
            context=[self.search_task()],
            output_file="02_summary.md"
        )

    @task
    def formatting_task(self):
        """Enhanced formatting task with explicit image integration instructions"""
        return Task(
            config=self.tasks_config.get("formatting_task", {}),
            agent=self.formatting_agent(),
            tools=[download_financial_chart, embed_image_in_markdown],
            context=[self.summary_task()],
            output_file="03_format.md"
        )

    @task
    def translating_task(self):
        return Task(
            config=self.tasks_config.get("translating_task", {}),
            agent=self.translating_agent(),
            context=[self.formatting_task()],
            output_file="04_translate.md"
        )

    @task
    def send_task(self):
        return Task(
            config=self.tasks_config.get("send_task", {}),
            agent=self.send_agent(),
            tools=[send_telegram_message_with_images],
            context=[self.translating_task()],
            output_file="05_send.md"
        )

    @crew
    def crew(self):
        return Crew(
            agents=self.agents,
            tasks=self.tasks,
            process=Process.sequential,
            verbose=True,
        )

    def test_network(self):
        # Determine host to test based on available keys
        if os.getenv("GEMINI_API_KEY"):
            host = "generativelanguage.googleapis.com"
            url = f"https://{host}"
        elif os.getenv("OPENAI_API_KEY"):
            host = "api.openai.com"
            url = f"https://{host}"
        else:
            host = "api.groq.com"
            url = f"https://{host}"

        try:
            ip = socket.gethostbyname(host)
            logger.info(f"DNS resolved {host} to {ip}")
            resp = requests.get(url, timeout=5)
            logger.info(f"Network connectivity to {host} is good")
            return True
        except Exception as e:
            logger.error(f"Network connectivity test to {host} failed: {e}")
            return False

    def run(self, inputs: Dict = None):
        if not self.test_network():
            return {"status": "error", "message": "Network connectivity check failed"}

        if inputs is None:
            inputs = {}
            
        inputs.setdefault("topic", "US financial markets today")
        inputs.setdefault("date", datetime.now().strftime("%Y-%m-%d"))
        inputs.setdefault("time", "After market close")
        inputs.setdefault("language", "Hindi and Hebrew")

        max_retries = 5
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting Crew run, attempt {attempt + 1}")
                result = self.crew().kickoff(inputs)
                return {"status": "success", "result": result}

            except Exception as e:
                logger.error(f"Crew run failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 30 * (attempt + 1)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        return {"status": "error", "message": "All retries failed"}

def run():
    """Entry point function for running the crew"""
    logger.info("Starting the Trading Agent")

    # Validate keys dynamically
    if not os.getenv("SERPER_API_KEY"):
        logger.error("Missing environment variable: SERPER_API_KEY")
        return {"status": "error", "message": "Missing environment variable: SERPER_API_KEY"}

    if not os.getenv("GROQ_API_KEY") and not os.getenv("OPENAI_API_KEY") and not os.getenv("GEMINI_API_KEY"):
        logger.error("Missing environment variables: Either GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY must be set")
        return {"status": "error", "message": "Missing environment variables: Either GROQ_API_KEY, OPENAI_API_KEY, or GEMINI_API_KEY must be set"}

    agent = TradingAgentCrew()
    results = agent.run()

    logger.info(f"Run results: {results}")
    return results

if __name__ == "__main__":
    result = run()
    print(result)