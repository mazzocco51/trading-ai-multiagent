from __future__ import annotations


def get_fear_and_greed() -> dict:
    try:
        import httpx

        resp = httpx.get("https://api.alternative.me/fng/", timeout=10)
        resp.raise_for_status()
        data = resp.json()["data"][0]
        return {
            "value": int(data["value"]),
            "label": data["value_classification"],
            "degraded": False,
        }
    except Exception:
        return {"value": None, "label": None, "degraded": True}
