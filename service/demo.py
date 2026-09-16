"""An offline end-to-end demonstration over real PostgreSQL and HTTP endpoints."""
from uuid import uuid4

from fastapi.testclient import TestClient

from service.api import create_app
from service.repository import load_seed
from service.replay import replay


def run_demo(repository, operator_key):
    wid = "demo-" + uuid4().hex[:12]
    repository.seed(wid)
    client = TestClient(create_app(repository, operator_key, wid))
    private = {"X-Cartly-Service-Key": operator_key}
    steps = []
    user = next(u for u in load_seed()["users"] if u["user_id"] == "U018")
    credentials = {"user_id": user["user_id"], "email": user["email"]}
    logged = client.post("/v1/sessions", headers=private, json=credentials).json()
    token = logged["result"]["token"]
    headers = {**private, "Authorization": "Bearer " + token}

    def post(path, body, request_id):
        response = client.post(path, headers={**headers, "Idempotency-Key": request_id}, json=body)
        result = response.json()
        steps.append({"request": path, "arguments": body, "response": result})
        return result

    post("/v1/tools/verify_user", {"arguments": credentials}, "verify")
    post("/v1/messages", {"content": "I want to return my unused kurta from O0011."}, "message")
    post("/v1/condition", {"order_id": "O0011", "item_id": "I0011", "unused": True}, "condition")
    request = {"intent": "return", "order_id": "O0011", "item_id": "I0011", "reason": "change_of_mind"}
    quote = post("/v1/proposals", request, "quote")["result"]["proposal"]
    pid = quote["proposal_id"]
    blocked = post(f"/v1/proposals/{pid}/execute", {}, "too-early")
    assert not blocked["ok"]
    post(f"/v1/proposals/{pid}/acceptance", {"accept": True, "terms_hash": quote["terms_hash"]}, "agree")
    done = post(f"/v1/proposals/{pid}/execute", {}, "execute")
    assert done["ok"] and done["result"]["refund_amount"] == 1400
    assert post(f"/v1/proposals/{pid}/execute", {}, "execute") == done
    # Reconstruct the complete API to prove it holds no business/confirmation state.
    client = TestClient(create_app(repository, operator_key, wid))
    assert post(f"/v1/proposals/{pid}/execute", {}, "execute") == done
    rid = done["result"]["return"]["return_id"]
    completed = post(f"/v1/system/pickups/{rid}/complete", {}, "pickup")
    assert completed["ok"] and completed["result"]["refund"]["amount"] == 1400
    report = replay(repository, wid)
    assert report["pass"], report
    return {"world_id": wid, "reference_date": load_seed()["config"]["today"], "api_cost_usd": 0,
            "model_calls": 0, "steps": steps, "replay": report,
            "summary": "Blocked before consent; one return despite retries and restart; pickup issued ₹1,400 to UPI."}
