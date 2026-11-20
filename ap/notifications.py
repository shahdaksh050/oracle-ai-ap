import httpx

from .db import Actor, settings, transaction


def deliver(tenant):
    """A scheduler may run this command repeatedly. Notifications are at-least-once."""
    cfg = settings()
    actor = Actor(tenant, "notification-worker", "worker")
    hook = cfg.get("slack_webhooks", {}).get(tenant)
    if not hook:
        return {"delivered": 0, "status": "channel_unconfigured"}
    if not hook.startswith("https://hooks.slack.com/services/"):
        raise ValueError("Unexpected Slack destination")
    with transaction(actor) as db:
        item = db.execute("""SELECT o.*, w.stage,w.version current_version FROM outbox o JOIN workflow w ON
            (w.tenant,w.id)=(o.tenant,o.workflow_id) WHERE delivered IS NULL AND next_attempt<=now()
            ORDER BY next_attempt LIMIT 1 FOR UPDATE OF o SKIP LOCKED""").fetchone()
        if not item:
            return {"delivered": 0, "status": "idle"}
        key = (item["workflow_id"], item["version"], item["kind"])
        stale = item["kind"] == "executive_review" and (
            item["stage"] not in ("executive", "batch_executive")
            or item["current_version"] != item["version"]
        )
        try:
            if not stale:
                url = (
                    cfg["public_origin"].rstrip("/")
                    + "/?workflow="
                    + str(item["workflow_id"])
                )
                with httpx.Client(timeout=5, trust_env=False) as client:
                    resp = client.post(
                        hook,
                        json={
                            "text": f"AP workspace · {item['kind']} · Open the authenticated workflow: {url}"
                        },
                    )
                    resp.raise_for_status()
            db.execute(
                "UPDATE outbox SET delivered=now() WHERE (workflow_id,version,kind)=(%s,%s,%s)",
                key,
            )
        except httpx.HTTPError:
            db.execute(
                "UPDATE outbox SET attempts=attempts+1,next_attempt=now()+interval '5 minutes' WHERE (workflow_id,version,kind)=(%s,%s,%s)",
                key,
            )
            return {"delivered": 0, "status": "retry_scheduled"}
        return {"delivered": int(not stale), "status": "processed"}
