"""Minimal web research helpers: DuckDuckGo HTML search + readable page fetch. No API keys needed."""
import httpx, urllib.parse
from bs4 import BeautifulSoup

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

def ddg_search(query, max_results=8):
    r = httpx.get("https://html.duckduckgo.com/html/", params={"q": query}, headers=UA, timeout=25, follow_redirects=True)
    soup = BeautifulSoup(r.text, "html.parser")
    out = []
    for res in soup.select(".result")[:max_results]:
        a = res.select_one(".result__a"); sn = res.select_one(".result__snippet")
        if not a: continue
        href = a.get("href", "")
        if "uddg=" in href:
            href = urllib.parse.unquote(urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg", [href])[0])
        out.append({"title": a.get_text(" ", strip=True), "url": href,
                    "snippet": sn.get_text(" ", strip=True) if sn else ""})
    return out

def fetch_text(url, max_chars=12000):
    try:
        r = httpx.get(url, headers=UA, timeout=30, follow_redirects=True)
        if r.status_code != 200: return f"[HTTP {r.status_code}]"
        if "pdf" in r.headers.get("content-type",""): return "[PDF - not parsed]"
        soup = BeautifulSoup(r.text, "lxml")
        for t in soup(["script","style","noscript"]): t.decompose()
        return "\n".join(l.strip() for l in soup.get_text("\n").splitlines() if l.strip())[:max_chars]
    except Exception as e:
        return f"[ERROR {type(e).__name__}: {e}]"
