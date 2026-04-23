import json
import os
import urllib.request


BASE = os.environ.get("BASE", "http://localhost:8001")


def post(path: str, obj: dict) -> dict:
    data = json.dumps(obj).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def get(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=15) as resp:
        body = resp.read()
        return json.loads(body) if body else {}


def main() -> None:
    print("healthz", get("/healthz"))
    print("reset", post("/v1/admin/demo/reset", {}))
    c = post("/v1/comments", {"username": "t1", "content": "hello idiot"})
    print("create_comment.action", c["comment"]["moderation"]["action"])
    cid = c["comment"]["id"]
    # translation requires volc config; if not configured, it returns 400
    try:
        tr = post(f"/v1/comments/{cid}/translate", {"target_lang": "zh"})
        print("translate.cached", tr.get("cached"), "len", len(tr.get("translated_text", "")))
    except Exception as e:  # noqa: BLE001
        print("translate.error", type(e).__name__, str(e)[:200])

    # WebAuthn endpoints: options call should work (verify needs browser)
    opt = post("/v1/auth/webauthn/register/options", {"username": "t1"})
    print("webauthn.register.options", "ok", isinstance(opt, dict))


if __name__ == "__main__":
    main()

