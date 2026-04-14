"""
Navi AI Agent
Terminal chat client for the Navi ERPNext copilot.
"""

import os

import anthropic
from dotenv import load_dotenv

from erpnext_client import ERPNextClient
from navi_core import (
    MODEL_NAME,
    SYSTEM_PROMPT,
    TOOLS,
    execute_tool,
    format_confirmed_action_result,
    is_affirmative,
    is_negative,
    json_result,
)

load_dotenv()


def main():
    print("\nStarting Navi AI Agent...")
    print("-" * 50)

    erp_client = ERPNextClient(
        base_url=os.getenv("ERPNEXT_URL", "http://localhost:8080"),
        username=os.getenv("ERPNEXT_USERNAME", "Administrator"),
        password=os.getenv("ERPNEXT_PASSWORD", "admin"),
    )
    claude = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    print("Connected to Claude AI")
    print("-" * 50)
    print("\nNavi is ready. Type your message or 'quit' to exit.\n")

    messages = []
    pending_action = None

    while True:
        user_input = input("You: ").strip()

        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q"}:
            print("\nGoodbye!\n")
            break

        if pending_action:
            if is_affirmative(user_input):
                confirmed_input = dict(pending_action["tool_input"])
                confirmed_input["confirmed"] = True
                result = execute_tool(pending_action["tool_name"], confirmed_input, erp_client)
                pending_action = None
                reply = format_confirmed_action_result(result)
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": reply})
                print(f"\nNavi: {reply}\n")
                continue

            if is_negative(user_input):
                pending_action = None
                reply = "Okay, I canceled that action."
                messages.append({"role": "user", "content": user_input})
                messages.append({"role": "assistant", "content": reply})
                print(f"\nNavi: {reply}\n")
                continue

            reply = "I am waiting for confirmation. Reply yes to continue or no to cancel."
            messages.append({"role": "user", "content": user_input})
            messages.append({"role": "assistant", "content": reply})
            print(f"\nNavi: {reply}\n")
            continue

        messages.append({"role": "user", "content": user_input})

        response = claude.messages.create(
            model=MODEL_NAME,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        while response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue

                print(f"  Executing: {block.name}...")
                result = execute_tool(block.name, block.input, erp_client)
                if result.get("status") == "confirmation_required":
                    pending_action = {"tool_name": block.name, "tool_input": block.input}

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json_result(result),
                    }
                )

            messages.append({"role": "user", "content": tool_results})

            response = claude.messages.create(
                model=MODEL_NAME,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=TOOLS,
                messages=messages,
            )

        final_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        print(f"\nNavi: {final_text}\n")
        messages.append({"role": "assistant", "content": response.content})


if __name__ == "__main__":
    main()
