"""The one active product prompt, used by web and terminal conversations."""
from service.repository import ROOT, digest

PROMPT_PATH = ROOT / "prompts/current.md"


def effective_prompt(world, policy):
    return PROMPT_PATH.read_text() + f"\nToday's date is {world['config']['today']} (IST).\n\n" + policy


def prompt_info(world, policy):
    text = effective_prompt(world, policy)
    title = next(line for line in policy.splitlines() if "Cartly Customer Support Policy" in line)
    return {"promptSource": "prompts/current.md", "policySource": "policy.md (version saved with this sandbox)",
            "policyTitle": title.lstrip("# "), "promptHash": digest(text), "prompt": text, "policy": policy}
