import json
import os

import pytest

from ap import adapters


def test_staging_and_independent_release_contract(pilot, monkeypatch):
    # This exercises the release state machine only. Real containment has its own test below.
    p = pilot
    monkeypatch.setattr(
        adapters, "sandbox", lambda code, aliases: (True, "Test double passed")
    )
    staged = p.request(
        "POST", "/adapters", json={"aliases": {"bill no": "number"}}
    ).json()
    assert staged["status"] == "staged"
    url = "/adapters/" + staged["id"] + "/release"
    assert p.request("POST", url, "clerk").status_code == 403
    assert p.request("POST", url, "qa", other=True).status_code == 404
    assert p.request("POST", url, "qa").json()["status"] == "released"
    same = p.request(
        "POST", "/adapters", "qa", json={"aliases": {"order date": "date"}}
    ).json()
    assert (
        p.request("POST", "/adapters/" + same["id"] + "/release", "qa").status_code
        == 409
    )


@pytest.mark.skipif(
    not os.environ.get("AP_GVISOR_TEST_IMAGE"),
    reason="requires a dedicated gVisor runner and approved image digest",
)
def test_gvisor_runtime_limits(pilot):
    p = pilot
    cfg = json.loads(p.cfg.read_text())
    cfg["sandbox_image"] = os.environ["AP_GVISOR_TEST_IMAGE"]
    p.cfg.write_text(json.dumps(cfg))
    aliases = {"bill": "number"}
    code = adapters.canonical(aliases)
    assert adapters.sandbox(code, aliases)[0]
    assert not adapters.sandbox("import time\ntime.sleep(5)\n" + code, aliases)[0]
    assert not adapters.sandbox("buffer=bytearray(140*1024*1024)\n" + code, aliases)[0]
