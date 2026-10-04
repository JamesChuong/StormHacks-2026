"""Assemble an agent's prompt, stream a Gemini response, and extract the code."""
import random
import re
import time

from . import config

BASE_SYSTEM = (
    "You are an AI coding agent competing in a live programming contest. "
    "Solve the problem in Python 3. Read input from stdin and write output to stdout. "
    "Reply with exactly one ```python code block containing the full solution."
)

SKILL_TEMPLATES = [
    {"name": "Edge cases first",
     "instructions": "Before coding, list edge cases (empty input, duplicates, negatives, "
                     "single element, large values) and make sure the solution handles each."},
    {"name": "Optimize for large inputs",
     "instructions": "Assume inputs up to 5*10^4 elements. Avoid O(n^2) algorithms and read "
                     "input with sys.stdin for speed."},
    {"name": "Be concise",
     "instructions": "Keep the solution short. No explanations outside the code block."},
]


def build_prompt(agent, challenge, feedback=""):
    system = BASE_SYSTEM
    if agent.get("system_prompt"):
        system += "\n\n" + agent["system_prompt"][:config.MAX_PROMPT_CHARS]
    skills = agent.get("skills") or []
    if skills:
        system += "\n\nSkills to apply on every challenge:\n" + "\n".join(
            f"- {s['name']}: {s['instructions']}" for s in skills[:config.MAX_SKILLS])

    examples = "\n\n".join(
        f"Example {i + 1}\nInput:\n{ex['input']}\nOutput:\n{ex['output']}"
        for i, ex in enumerate(challenge["examples"]))
    user = f"# {challenge['title']}\n\n{challenge['statement']}\n\n{examples}"
    if feedback:
        user += f"\n\nYour previous submission failed:\n{feedback}\nFix it and resubmit."
    return system, user


CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL)


def extract_code(text):
    blocks = CODE_RE.findall(text)
    if blocks:
        return blocks[-1].strip()
    # Unterminated block (e.g. hit token limit): take everything after the fence.
    if "```" in text:
        return text.split("```", 1)[1].split("\n", 1)[-1].strip()
    return text.strip()


def _stream_gemini(agent, system, user, on_chunk):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    tokens = 0
    text = ""
    for chunk in client.models.generate_content_stream(
            model=agent["model"], contents=user,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0.7)):
        if chunk.text:
            text += chunk.text
            on_chunk(chunk.text)
        if chunk.usage_metadata and chunk.usage_metadata.total_token_count:
            tokens = chunk.usage_metadata.total_token_count
    return text, tokens


def _stream_mock(challenge, attempt, on_chunk):
    """Stream the reference solution, sometimes broken on the first try."""
    code = challenge["reference_solution"]
    if attempt == 1 and random.random() < 0.35:
        code = "import sys\ndata = sys.stdin.read().split()\nprint(0)\n"
    text = f"```python\n{code}\n```"
    for i in range(0, len(text), 12):
        on_chunk(text[i:i + 12])
        time.sleep(random.uniform(0.02, 0.08))
    return text, len(text) // 4


def solve(agent, challenge, attempt=1, feedback="", on_chunk=lambda c: None):
    """Return (code, tokens_used)."""
    system, user = build_prompt(agent, challenge, feedback)
    if agent["model"] == "mock" or not config.GEMINI_API_KEY:
        text, tokens = _stream_mock(challenge, attempt, on_chunk)
    else:
        text, tokens = _stream_gemini(agent, system, user, on_chunk)
    return extract_code(text), tokens


class ChunkBuffer:
    """Batch streamed chunks so we publish every ~150ms instead of per token."""

    def __init__(self, flush, interval=0.15):
        self.flush_fn, self.interval = flush, interval
        self.buf, self.last = "", time.time()

    def add(self, chunk):
        self.buf += chunk
        if time.time() - self.last >= self.interval:
            self.flush()

    def flush(self):
        if self.buf:
            self.flush_fn(self.buf)
        self.buf, self.last = "", time.time()
