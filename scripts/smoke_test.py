import json
import os
import urllib.request


BASE = os.environ.get("PROTECT_ZYY_BASE", "http://127.0.0.1:8002")


def post(path: str, obj: dict) -> dict:
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())

def post_empty(path: str) -> dict:
    req = urllib.request.Request(BASE + path, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = resp.read() or b"{}"
        return json.loads(body)


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read())


def main() -> None:
    # Clean slate
    try:
        post_empty("/v1/admin/demo/reset")
    except Exception:
        pass

    r1 = post("/v1/comments", {"username": "u1", "content": "you are trash"})
    r2 = post("/v1/comments", {"username": "u1", "content": "idiot"})
    r3 = post("/v1/comments", {"username": "u1", "content": "stupid"})
    r4 = post("/v1/comments", {"username": "u2", "content": "下头!!!"})
    list_ = get("/v1/comments?limit=5")
    queue = get("/v1/review-queue?limit=5")

    comment_id = r1["comment"]["id"]
    over = post(
        f"/v1/admin/comments/{comment_id}/override",
        {"new_action": "ALLOW", "reason": "good-faith", "moderator": "admin"},
    )

    out = {
        "created_actions": [
            r1["comment"]["moderation"]["action"],
            r2["comment"]["moderation"]["action"],
            r3["comment"]["moderation"]["action"],
        ],
        "user_banned": r3["user"]["is_banned"],
        "user_strikes": r3["user"]["strikes"],
        "mild_neg_action": r4["comment"]["moderation"]["action"],
        "list_total": list_["total"],
        "queue_total": queue["total"],
        "override_action": over["comment"]["moderation"]["action"],
        "override_user_strikes": over["user"]["strikes"],
    }
    print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    main()

