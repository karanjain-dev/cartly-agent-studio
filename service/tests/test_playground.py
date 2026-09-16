from datetime import date

from service.playground import ADDITIONS, ensure_playground
from service.repository import load_seed


def test_new_customer_and_order_fixtures_are_valid():
    seed = load_seed()
    today = date.fromisoformat(seed["config"]["today"])
    assert len(ADDITIONS["users"]) == 20
    assert len(ADDITIONS["orders"]) == len(ADDITIONS["order_items"]) == 100
    for table, key in [("users", "user_id"), ("orders", "order_id"), ("order_items", "item_id"),
                       ("users", "email"), ("users", "phone")]:
        values = [r[key] for r in seed[table] + ADDITIONS[table]]
        assert len(values) == len(set(values))
    users = {u["user_id"] for u in ADDITIONS["users"]}
    orders = {o["order_id"]: o for o in ADDITIONS["orders"]}
    for uid in users:
        assert sum(o["user_id"] == uid for o in orders.values()) == 5
    for o in orders.values():
        assert o["user_id"] in users
        assert 0 <= o["shipping_fee"] <= 99
        assert o["delivery_address"]["pincode"] in seed["serviceable_pincodes"]["serviceable_pincodes"]
        placed = date.fromisoformat(o["placed_date"])
        assert placed <= today
        assert date.fromisoformat(o["promised_delivery_date"]) >= placed
        assert (o["actual_delivery_date"] is not None) == (o["status"] == "Delivered")
        if o["actual_delivery_date"]:
            assert placed <= date.fromisoformat(o["actual_delivery_date"]) <= today
    for i in ADDITIONS["order_items"]:
        assert i["order_id"] in orders and i["price"] > 0 and i["quantity"] == 1
        assert isinstance(i["evidence_photo_uploaded"], bool)
        assert all(k in i for k in ["ordered_size", "delivered_size", "ordered_color", "delivered_color",
                                    "ordered_product_name", "delivered_product_name", "ordered_quantity", "delivered_quantity"])


def test_playground_import_is_idempotent_under_concurrency(repo, sandbox):
    from concurrent.futures import ThreadPoolExecutor
    wid, _ = sandbox
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda _: ensure_playground(repo, wid), range(3)))
    world = repo.snapshot(wid)
    assert len(world["users"]) == len(load_seed()["users"]) + 20
    assert len(world["orders"]) == len(load_seed()["orders"]) + 100
    assert repo.verify_audit(wid)["pass"]
