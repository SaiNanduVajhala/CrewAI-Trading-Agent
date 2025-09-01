#!/usr/bin/env python3

import os
import logging
import requests
import socket
import time
from datetime import datetime
from typing import Dict

from crewai import Agent, Crew, Process, Task
from crewai.project import CrewBase, agent, task, crew
from crewai_tools import SerperDevTool
import litellm

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@CrewBase
class TradingAgentCrew:
    agents_config = 'config/agents.yaml'
    tasks_config = 'config/tasks.yaml'

    def __init__(self):
        self.primary_llm = "groq/llama-3.3-70b-versatile"
        self.secondary_llm = "groq/llama-3.1-8b-instant"

    @agent
    def search_agent(self):
        return Agent(
            config=self.agents_config["search_agent"],
            tools=[SerperDevTool(api_key=os.getenv("SERPER_API_KEY"))],
            llm=self.primary_llm,
            verbose=True,
        )

    @agent
    def summary_agent(self):
        return Agent(
            config=self.agents_config["summary_agent"],
            llm=self.secondary_llm,
            verbose=True,
        )

    @agent
    def formatting_agent(self):
        return Agent(
            config=self.agents_config["formatting_agent"],
            llm=self.secondary_llm,
            verbose=True,
        )

    @agent
    def translating_agent(self):
        return Agent(
            config=self.agents_config["translating_agent"],
            llm=self.secondary_llm,
            verbose=True,
        )

    @agent
    def send_agent(self):
        return Agent(
            config=self.agents_config["send_agent"],
            llm=self.primary_llm,
            verbose=True,
        )

    @task
    def search_task(self):
        return Task(
            config=self.tasks_config["search_task"],
            agent=self.search_agent(),
            output_file="01_search.md"
        )

    @task
    def summary_task(self):
        return Task(
            config=self.tasks_config["summary_task"],
            agent=self.summary_agent(),
            context=[self.search_task()],
            output_file="02_summary.md"
        )

    @task
    def formatting_task(self):
        return Task(
            config=self.tasks_config["formatting_task"],
            agent=self.formatting_agent(),
            context=[self.summary_task()],
            output_file="03_format.md"
        )

    @task
    def translating_task(self):
        return Task(
            config=self.tasks_config["translating_task"],
            agent=self.translating_agent(),
            context=[self.formatting_task()],
            output_file="04_translate.md"
        )

    @task
    def send_task(self):
        return Task(
            config=self.tasks_config["send_task"],
            agent=self.send_agent(),
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
        try:
            ip = socket.gethostbyname("api.groq.com")
            logger.info(f"DNS resolved api.groq.com to {ip}")
            resp = requests.get("https://api.groq.com", timeout=5)
            resp.raise_for_status()
            logger.info("Network connectivity to api.groq.com is good")
            return True
        except Exception as e:
            logger.error(f"Network connectivity test failed: {e}")
            return False


    def run(self, inputs: Dict = None):
        if not self.test_network():
            return {"status": "error", "message": "Network connectivity check failed"}

        if inputs is None:
            inputs = {
                "topic": "US financial markets today",
                "date": datetime.now().strftime("%Y-%m-%d"),
                "time": "After market close"
            }

        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting Crew run, attempt {attempt + 1}")
                result = self.crew().kickoff(inputs)
                return {"status": "success", "result": result}

            except Exception as e:
                logger.error(f"Crew run failed: {e}")
                if attempt < max_retries - 1:
                    wait_time = 5 * (attempt + 1)
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)

        return {"status": "error", "message": "All retries failed"}


if __name__ == "__main__":
    logger.info("Starting the Trading Agent")

    required_envs = ["GROQ_API_KEY", "SERPER_API_KEY"]  
    missing = [var for var in required_envs if not os.getenv(var)]
    if missing:
        logger.error(f"Missing environment variables: {missing}")
        exit(1)

    agent = TradingAgentCrew()
    results = agent.run()

    logger.info(f"Run results: {results}")
    print(results)
