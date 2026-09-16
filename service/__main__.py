"""Run with python -m service: setup, demo, serve, chat, replay, or reset."""
import argparse
import json
from uuid import uuid4

from service.core import CartlyService
from service.local import repository, operator_key, STATE_DIR
from service.repository import load_seed
from service.playground import ensure_playground, shared_world_id


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["setup", "demo", "serve", "chat", "replay", "reset"])
    parser.add_argument("--world", default="development")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--user", default="U018")
    parser.add_argument("--enable-model", action="store_true", help="Opt in to paid API calls; requires OPENAI_API_KEY")
    args = parser.parse_args()
    repo = repository()
    if args.command == "reset":
        # A reset is a NEW sandbox. Old actions, sessions and audit evidence survive.
        world = "development-" + uuid4().hex[:12]
        print(json.dumps(repo.seed(world), indent=2))
        print(f"Start a clean sandbox: python -m service serve --world {world}")
        return
    if args.command in {"setup", "serve", "chat"}:
        args.world = shared_world_id(args.world)
        ensure_playground(repo, args.world)
    if args.command == "setup":
        operator_key()
        state = repo.snapshot(args.world)
        print(json.dumps({"world": args.world, "reference_date": state["config"]["today"],
                          "records": {k: len(v) for k, v in state.items() if isinstance(v, list)}}, indent=2))
    elif args.command == "demo":
        from service.demo import run_demo
        result = run_demo(repo, operator_key())
        output = STATE_DIR / "latest-demo.json"
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(result["summary"])
        print("Replay passed:", result["replay"]["pass"])
        print("API cost: $0.00; actual PostgreSQL actions, no model calls.")
        print("Saved evidence:", output)
        print("Sandbox:", result["world_id"])
    elif args.command == "replay":
        from service.replay import replay
        report = replay(repo, args.world)
        print(json.dumps(report, indent=2))
        if not report["pass"]:
            raise SystemExit(1)
    elif args.command == "serve":
        import uvicorn
        from service.api import create_app
        transport = None
        if args.enable_model:
            from service.agent import OpenAITransport, load_api_key
            transport = OpenAITransport(load_api_key())
        app = create_app(repo, operator_key(), args.world, transport)
        print(f"Cartly API: http://127.0.0.1:{args.port}/docs — sandbox {args.world}")
        uvicorn.run(app, host="127.0.0.1", port=args.port)
    elif args.command == "chat":
        if not args.enable_model:
            parser.error("chat makes paid API calls; add --enable-model, or use demo for the $0 walkthrough")
        from service.agent import PersistentAgent, OpenAITransport, load_api_key
        s = CartlyService(repo)
        u = next((u for u in repo.snapshot(args.world)["users"] if u["user_id"] == args.user), None)
        if not u:
            parser.error("Unknown demo user")
        credentials = {"user_id": u["user_id"], "email": u["email"]}
        token = s.login(args.world, **credentials)["result"]["token"]
        s.tool(token, "verify_user", credentials)
        agent = PersistentAgent(s, OpenAITransport(load_api_key()))
        print(f"Cartly / {args.user}. Paid API enabled. /quit exits.")
        print("Use /unused ORDER ITEM yes|no to state condition. Review each proposal before entering /accept or /decline.")
        proposal = None
        while True:
            try:
                text = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if text == "/quit":
                break
            if not text:
                continue
            if text.startswith("/unused "):
                parts = text.split()
                if len(parts) != 4 or parts[3] not in {"yes", "no"}:
                    print("Use /unused ORDER ITEM yes|no")
                    continue
                result = s.assert_unused(token, parts[1], parts[2], parts[3] == "yes", str(uuid4()))
                proposal = None
                print(json.dumps(result))
            elif text in {"/accept", "/decline"} and proposal:
                result = s.accept(token, proposal["proposal_id"], proposal["terms_hash"], text == "/accept", str(uuid4()))
                if result["ok"] and text == "/accept":
                    result = s.execute(token, proposal["proposal_id"], str(uuid4()))
                print(json.dumps(result, ensure_ascii=False, indent=2))
                proposal = None
            else:
                result = agent.reply(token, text, str(uuid4()))
                if result["ok"]:
                    print("Cartly:", result["result"]["message"])
                    proposal = result["result"].get("proposal")
                    if proposal:
                        print("Review the proposal above. /accept agrees to those exact terms; /decline refuses.")
                else:
                    print(json.dumps(result))


if __name__ == "__main__":
    main()
