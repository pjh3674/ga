#!/usr/bin/env python3
import sys
import os
import json
from pathlib import Path

# Add the project directory to sys.path
BASE_DIR = Path(__file__).parent
sys.path.append(str(BASE_DIR))

try:
    from debate import run_debate
    from db import save_debate
    from config import DEFAULT_BACKEND_KEY
except ImportError as e:
    print(f"Import error: {e}")
    sys.exit(1)

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 run_cli_debate.py '<topic>' [persona] [backend] [--rag] [--web] [--khoj]")
        sys.exit(1)

    flags = set(sys.argv)
    use_rag = "--rag" in flags
    use_web = "--web" in flags
    use_khoj = "--khoj" in flags
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]

    topic = positional[0]
    persona = positional[1] if len(positional) > 1 else "balanced"
    backend = positional[2] if len(positional) > 2 else DEFAULT_BACKEND_KEY

    print(f"Starting debate on: {topic}")
    print(f"Persona: {persona}, Backend: {backend}")
    print(f"RAG: {use_rag} | Web: {use_web} | Khoj: {use_khoj}")
    print("-" * 50)

    # Prepare agent backends mapping
    agent_backends = {
        "pro": backend,
        "con": backend,
        "judge": backend,
        "fact": backend,
        "audience": backend
    }

    try:
        messages = run_debate(
            topic=topic,
            persona=persona,
            agent_backends=agent_backends,
            use_rag=use_rag,
            use_web_search=use_web,
            use_khoj=use_khoj,
        )

        # Extract verdict
        verdict = ""
        for m in reversed(messages):
            if m.get("name") == "judge" and "판정:" in m.get("content", ""):
                verdict = m["content"]
                break

        # Save to DB
        debate_id = save_debate(topic, messages, verdict)
        print(f"\nDebate saved with ID: {debate_id}")

        # Save to Obsidian
        try:
            from integrations.obsidian_save import save_to_obsidian
            _sr = save_to_obsidian(topic, messages, verdict, debate_id)
            print(f"Obsidian saved: {_sr.vault_path} | status: {_sr.status_line()}")
            if _sr.errors:
                print(f"  경고: {' | '.join(_sr.errors)}")
        except Exception as obs_e:
            print(f"Obsidian save failed: {obs_e}")
        print("-" * 50)

        # Output the debate
        for m in messages:
            name = m.get("name", "unknown")
            content = m.get("content", "").strip()
            if not content: continue
            
            # Skip noise if possible or just print all
            print(f"[{name.upper()}]")
            print(content)
            print("-" * 30)

        print(f"\n[FINAL VERDICT]")
        print(verdict)

    except Exception as e:
        print(f"Error during debate: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
