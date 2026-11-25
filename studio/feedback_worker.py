"""Read canonical context and prior turns from stdin; output only a successful model reply."""

import json
import os
import sys

import httpx

from skillevaluator.evaluation.tier3_feedback_chat import Tier3FeedbackAssistant, Tier3FeedbackSession

if __name__ == "__main__":
    context, messages = json.load(sys.stdin)
    with httpx.Client(follow_redirects=False, trust_env=False, verify=os.getenv("SSL_CERT_FILE") or True) as transport:
        assistant = Tier3FeedbackAssistant(
            model=os.getenv("SKILL_EVAL_LLM_MODEL"), http_client=transport, max_retries=0
        )
        session = Tier3FeedbackSession(context, assistant=assistant)
        json.dump(assistant.chat([*session.transcript, *messages]), sys.stdout)
