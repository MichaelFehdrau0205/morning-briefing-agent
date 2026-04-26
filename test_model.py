"""
Milestone 1 — Model connects.
Run this first. If you get a one-sentence greeting back, you're good.

    python test_model.py
"""

import os
from dotenv import load_dotenv
from strands import Agent
from strands.models.litellm import LiteLLMModel

load_dotenv()

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise EnvironmentError("OPENROUTER_API_KEY not found in .env — add it and try again.")

model = LiteLLMModel(
    client_args={
        "api_key": api_key,
        "api_base": "https://openrouter.ai/api/v1",
    },
    model_id="openrouter/tencent/hy3-preview:free",
    params={"max_tokens": 2048},
)

agent = Agent(model=model)

print("Connecting to model...\n")
response = agent("Say hello and tell me what model you are in one sentence.")
print(response)
