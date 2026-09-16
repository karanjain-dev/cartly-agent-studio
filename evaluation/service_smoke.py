"""Zero-model integration check of the current service against the frozen oracle."""
import json

from service.demo import run_demo
from service.local import repository, operator_key, STATE_DIR
from service.repository import load_seed
from simulation.reference_calculator import calculate


def main():
    repo = repository()
    expected = calculate(load_seed(), "U018", {"order_id": "O0011", "item_id": "I0011",
        "intent": "return", "reason": "change_of_mind", "is_unused": True})
    result = run_demo(repo, operator_key())
    final = repo.snapshot(result["world_id"])
    actual = next(r for r in final["refunds"] if r["order_id"] == "O0011")
    passed = (actual["amount"] == expected["refund_amount"]
              and actual["shipping_refunded"] == expected["shipping_refunded"]
              and actual["method"] == expected["refund_method"] and result["replay"]["pass"])
    report = {"kind": "deterministic_service_integration_not_model_accuracy", "pass": passed,
              "expected": expected, "actual_refund": actual, **result}
    path = STATE_DIR / "service-smoke.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"pass": passed, "cost_usd": 0, "report": str(path)}, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
