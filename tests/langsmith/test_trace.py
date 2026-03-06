#!/usr/bin/env python
"""
Standalone LangSmith tracing verification script.

Run directly: python -m tests.langsmith.test_trace
NOT a pytest test — module-level side effects and @traceable decorator
conflict with pytest fixture injection.
"""
import os
import time
from app.core.config import settings

# Ensure env vars are set for LangSmith SDK
os.environ['LANGSMITH_TRACING'] = str(settings.LANGSMITH_TRACING).lower()
os.environ['LANGSMITH_API_KEY'] = settings.LANGSMITH_API_KEY
os.environ['LANGSMITH_PROJECT'] = settings.LANGSMITH_PROJECT
os.environ['LANGSMITH_ENDPOINT'] = settings.LANGSMITH_ENDPOINT


def _main():
    print("=" * 60)
    print("LangSmith Tracing Test")
    print("=" * 60)
    print()
    print("Configuration:")
    print(f"  LANGSMITH_TRACING: {os.getenv('LANGSMITH_TRACING')}")
    print(f"  LANGSMITH_API_KEY: {os.getenv('LANGSMITH_API_KEY', '')[:20]}...")
    print(f"  LANGSMITH_PROJECT: {os.getenv('LANGSMITH_PROJECT')}")
    print(f"  LANGSMITH_ENDPOINT: {os.getenv('LANGSMITH_ENDPOINT')}")
    print()

    # Import after setting env vars
    from langsmith import traceable, Client

    @traceable(name="elephantasm_test", tags=["test", "manual", "verification"])
    def traced_function(name: str) -> dict:
        """Simple function to test tracing."""
        print(f"  -> Executing traced function with input: {name}")
        time.sleep(0.2)
        return {
            "status": "success",
            "message": f"Hello from {name}!",
            "timestamp": time.time()
        }

    print("Executing traced function...")
    result = traced_function("Elephantasm")
    print(f"  -> Result: {result}")
    print()

    # Try to initialize client to verify connection
    print("Verifying LangSmith connection...")
    try:
        client = Client()
        print(f"  LangSmith client connected!")
        print(f"   API URL: {client.api_url}")
        print()
    except Exception as e:
        print(f"  Failed to connect to LangSmith: {e}")
        print()

    print("=" * 60)
    print("Check your LangSmith dashboard:")
    print("https://smith.langchain.com/projects/pr-drab-sigh-27")
    print()
    print("Note: Traces may take 5-10 seconds to appear")
    print("=" * 60)


if __name__ == "__main__":
    _main()
