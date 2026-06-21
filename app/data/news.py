from __future__ import annotations

import xml.etree.ElementTree as ET


def get_news_headlines(asset: str, limit: int = 10) -> list[dict]:
    ticker = asset.split("/")[0].upper()
    try:
        import httpx

        resp = httpx.get("https://cryptopanic.com/news/rss/", timeout=10)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
        items = root.findall(".//item")
        results = []
        for item in items:
            title = item.findtext("title") or ""
            if ticker.lower() not in title.lower():
                continue
            results.append(
                {
                    "title": title,
                    "published": item.findtext("pubDate") or "",
                    "url": item.findtext("link") or "",
                }
            )
            if len(results) >= limit:
                break
        return results
    except Exception:
        return []
