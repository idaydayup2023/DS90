from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
import re
import urllib.request
import urllib.parse

from ..imdb_bootstrap import resolve_imdbpy_python


@dataclass(frozen=True)
class ImdbTitle:
    imdb_id: str
    kind: str
    title: str | None
    year: int | None
    rating: float | None
    votes: int | None
    canonical_title: str | None
    canonical_year: int | None
    series_title: str | None
    franchise_root: str | None


@dataclass(frozen=True)
class ImdbLookupDebug:
    status: str  # ok|not_found|error|cached|invalid
    error: str | None
    candidates: tuple[dict[str, Any], ...]


def _cache_key(kind: str, title: str | None, year: int | None) -> str:
    h = hashlib.sha1()
    h.update((kind or "").encode("utf-8"))
    h.update(b"\0")
    h.update((title or "").encode("utf-8"))
    h.update(b"\0")
    h.update(str(year or "").encode("utf-8"))
    return h.hexdigest()


def _safe_json_loads(text: str) -> dict[str, Any]:
    t = text.strip()
    if not t:
        raise ValueError("empty imdb output")
    obj = json.loads(t)
    if not isinstance(obj, dict):
        raise ValueError("imdb output is not an object")
    return obj


def _as_int(v: Any) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except Exception:
        return None


def _as_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def _as_str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


class ImdbMcp:
    def __init__(self, cache_dir: Path, auto_install: bool, ttl_days: int = 30):
        self._cache_dir = cache_dir
        self._auto_install = auto_install
        self._ttl_seconds = max(0, int(ttl_days)) * 86400
        self._cache_path = cache_dir / "imdb_cache"
        self._cache_path.mkdir(parents=True, exist_ok=True)

    def lookup(self, kind: str, title: str | None, year: int | None) -> ImdbTitle | None:
        t, _dbg = self.lookup_debug(kind=kind, title=title, year=year)
        return t

    def lookup_debug(self, kind: str, title: str | None, year: int | None) -> tuple[ImdbTitle | None, ImdbLookupDebug]:
        kind = (kind or "").lower()
        if kind not in ("movie", "tv"):
            return None, ImdbLookupDebug(status="invalid", error="unsupported kind", candidates=())
        if not title:
            return None, ImdbLookupDebug(status="invalid", error="missing title", candidates=())

        key = _cache_key(kind, title, year)
        p = self._cache_path / f"{key}.json"
        now = int(time.time())
        if p.exists() and self._ttl_seconds > 0:
            try:
                if now - int(p.stat().st_mtime) <= self._ttl_seconds:
                    obj = _safe_json_loads(p.read_text(encoding="utf-8", errors="replace"))
                    return self._to_title(obj), ImdbLookupDebug(status="cached", error=None, candidates=())
            except Exception:
                pass

        out = self._query(kind=kind, title=title, year=year)
        if out is None:
            return None, ImdbLookupDebug(status="error", error="imdb query produced no output", candidates=())
        if isinstance(out.get("error"), str) and out.get("error"):
            return None, ImdbLookupDebug(status="error", error=str(out.get("error")), candidates=tuple(out.get("candidates") or ()))
        best = out.get("best")
        if best is None:
            sug = self._suggest(title)
            best2 = self._best_from_suggest(kind=kind, title=title, year=year, candidates=sug)
            if best2 is None:
                return None, ImdbLookupDebug(status="not_found", error=None, candidates=tuple(out.get("candidates") or ()))
            fetched = self._fetch_title(best2["imdb_id"])
            if fetched is None:
                return None, ImdbLookupDebug(status="error", error="imdb fetch failed after suggest", candidates=tuple(sug))
            try:
                p.write_text(json.dumps(fetched, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return self._to_title(fetched), ImdbLookupDebug(status="ok", error=None, candidates=tuple(sug))
        if not isinstance(best, dict):
            return None, ImdbLookupDebug(status="error", error="imdb output best is not object", candidates=tuple(out.get("candidates") or ()))
        try:
            p.write_text(json.dumps(best, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        title_obj = self._to_title(best)
        if title_obj.title is None and title_obj.rating is None and title_obj.votes is None:
            sug = self._suggest(title)
            best2 = self._best_from_suggest(kind=kind, title=title, year=year, candidates=sug)
            if best2 is not None:
                fetched = self._fetch_title(best2["imdb_id"])
                if fetched is not None:
                    try:
                        p.write_text(json.dumps(fetched, ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        pass
                    return self._to_title(fetched), ImdbLookupDebug(status="ok", error=None, candidates=tuple(sug))
        return title_obj, ImdbLookupDebug(status="ok", error=None, candidates=tuple(out.get("candidates") or ()))

    def lookup_by_id(self, imdb_tt: str) -> ImdbTitle | None:
        t, _dbg = self.lookup_by_id_debug(imdb_tt)
        return t

    def lookup_by_id_debug(self, imdb_tt: str) -> tuple[ImdbTitle | None, ImdbLookupDebug]:
        tt = (imdb_tt or "").strip().lower()
        if not tt.startswith("tt"):
            return None, ImdbLookupDebug(status="invalid", error="missing tt prefix", candidates=())
        digits = tt[2:]
        if not digits.isdigit():
            return None, ImdbLookupDebug(status="invalid", error="invalid tt digits", candidates=())
        key = _cache_key("id", tt, None)
        p = self._cache_path / f"{key}.json"
        now = int(time.time())
        if p.exists() and self._ttl_seconds > 0:
            try:
                if now - int(p.stat().st_mtime) <= self._ttl_seconds:
                    obj = _safe_json_loads(p.read_text(encoding="utf-8", errors="replace"))
                    return self._to_title(obj), ImdbLookupDebug(status="cached", error=None, candidates=())
            except Exception:
                pass

        out = self._query_by_id(movie_id=digits)
        if out is None:
            return None, ImdbLookupDebug(status="error", error="imdb id query produced no output", candidates=())
        if isinstance(out.get("error"), str) and out.get("error"):
            return None, ImdbLookupDebug(status="error", error=str(out.get("error")), candidates=())
        best = out.get("best")
        if best is None:
            fetched = self._fetch_title(tt)
            if fetched is None:
                return None, ImdbLookupDebug(status="not_found", error=None, candidates=())
            try:
                p.write_text(json.dumps(fetched, ensure_ascii=False), encoding="utf-8")
            except Exception:
                pass
            return self._to_title(fetched), ImdbLookupDebug(status="ok", error=None, candidates=())
        if not isinstance(best, dict):
            return None, ImdbLookupDebug(status="error", error="imdb id output best is not object", candidates=())
        try:
            p.write_text(json.dumps(best, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        title_obj = self._to_title(best)
        if title_obj.title is None and title_obj.rating is None and title_obj.votes is None:
            fetched = self._fetch_title(tt)
            if fetched is not None:
                try:
                    p.write_text(json.dumps(fetched, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return self._to_title(fetched), ImdbLookupDebug(status="ok", error=None, candidates=())
        return title_obj, ImdbLookupDebug(status="ok", error=None, candidates=())

    def _query(self, kind: str, title: str, year: int | None) -> dict[str, Any] | None:
        py = resolve_imdbpy_python(cache_dir=self._cache_dir, auto_install=self._auto_install)
        code = r"""
import json,sys
from imdb import Cinemagoer

kind=sys.argv[1]
title=sys.argv[2]
year=int(sys.argv[3]) if sys.argv[3] != "None" else None

def safe_out(**kw):
    print(json.dumps(kw, ensure_ascii=False))
    raise SystemExit(0)

try:
    ia=Cinemagoer()
    results=ia.search_movie(title)
except Exception as e:
    safe_out(error=f"search_movie failed: {type(e).__name__}: {e}", best=None, candidates=[])

def norm(s):
    return ''.join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()

def score(item):
    t=str(item.get('title') or '')
    y=item.get('year')
    k=str(item.get('kind') or '')
    s=0
    if kind == 'tv':
        if 'tv series' in k or 'tv mini series' in k or 'tv' in k:
            s += 50
        else:
            s -= 50
    else:
        if 'tv series' in k or 'tv mini series' in k:
            s -= 30
    if norm(title) and norm(title) in norm(t):
        s += 20
    if year and isinstance(y,int):
        s -= min(abs(y-year), 10) * 3
    return s

results=sorted(results, key=score, reverse=True)
best=results[0] if results else None
if not best:
    safe_out(best=None, candidates=[])

try:
    movie=ia.get_movie(best.movieID)
    try:
        ia.update(movie, info=['main', 'vote details'])
    except Exception:
        pass
except Exception as e:
    safe_out(error=f"get_movie failed: {type(e).__name__}: {e}", best=None, candidates=[{"imdb_id": str(r.movieID), "kind": str(r.get("kind") or ""), "title": str(r.get("title") or ""), "year": r.get("year")} for r in results[:5]])

connections=None
try:
    connections=ia.get_movie_connections(best.movieID)
except Exception:
    connections=None

def pick_franchise_root(connections_obj):
    if not connections_obj:
        return None
    for k in ('spin off from', 'spin-off from', 'spinoff from', 'followed by', 'followed by (tv)', 'featured in'):
        v=connections_obj.get(k)
        if v:
            try:
                first=v[0]
                return str(first.get('title') or None)
            except Exception:
                return None
    return None

out={
  "best": {
    "imdb_id": str(best.movieID),
    "kind": str(movie.get('kind') or best.get('kind') or ''),
    "title": str(movie.get('title') or best.get('title') or ''),
    "year": movie.get('year'),
    "rating": movie.get('rating'),
    "votes": movie.get('votes'),
    "canonical_title": str(movie.get('title') or best.get('title') or ''),
    "canonical_year": movie.get('year'),
    "series_title": str(movie.get('title') or best.get('title') or '') if kind=='tv' else None,
    "franchise_root": pick_franchise_root(connections),
  },
  "candidates": [
    {"imdb_id": str(r.movieID), "kind": str(r.get('kind') or ''), "title": str(r.get('title') or ''), "year": r.get('year')}
    for r in results[:5]
  ],
}
print(json.dumps(out, ensure_ascii=False))
"""
        args = [py, "-c", code, kind, title, str(year)]
        p = subprocess.run(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=os.environ.copy(),
            timeout=120,
        )
        if not (p.stdout or "").strip():
            err = (p.stderr or "").strip()
            return {"error": err or f"imdb subprocess failed rc={p.returncode}", "best": None, "candidates": []}
        obj = _safe_json_loads(p.stdout or "")
        if p.returncode != 0 and "error" not in obj:
            err = (p.stderr or "").strip()
            obj["error"] = err or f"imdb subprocess failed rc={p.returncode}"
        if "candidates" not in obj:
            obj["candidates"] = []
        return obj

    def _query_by_id(self, movie_id: str) -> dict[str, Any] | None:
        py = resolve_imdbpy_python(cache_dir=self._cache_dir, auto_install=self._auto_install)
        code = r"""
import json,sys
from imdb import Cinemagoer

movie_id=sys.argv[1]

def safe_out(**kw):
    print(json.dumps(kw, ensure_ascii=False))
    raise SystemExit(0)

try:
    ia=Cinemagoer()
except Exception as e:
    safe_out(error=f"init failed: {type(e).__name__}: {e}", best=None)

try:
    movie=ia.get_movie(movie_id)
    try:
        ia.update(movie, info=['main', 'vote details'])
    except Exception:
        pass
except Exception as e:
    safe_out(error=f"get_movie failed: {type(e).__name__}: {e}", best=None)

connections=None
try:
    connections=ia.get_movie_connections(movie_id)
except Exception:
    connections=None

def pick_franchise_root(connections_obj):
    if not connections_obj:
        return None
    for k in ('spin off from', 'spin-off from', 'spinoff from', 'followed by', 'followed by (tv)', 'featured in'):
        v=connections_obj.get(k)
        if v:
            try:
                first=v[0]
                return str(first.get('title') or None)
            except Exception:
                return None
    return None

out={
  "best": {
    "imdb_id": str(movie_id),
    "kind": str(movie.get('kind') or ''),
    "title": str(movie.get('title') or ''),
    "year": movie.get('year'),
    "rating": movie.get('rating'),
    "votes": movie.get('votes'),
    "canonical_title": str(movie.get('title') or ''),
    "canonical_year": movie.get('year'),
    "series_title": None,
    "franchise_root": pick_franchise_root(connections),
  }
}
print(json.dumps(out, ensure_ascii=False))
"""
        p = subprocess.run(
            [py, "-c", code, movie_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            env=os.environ.copy(),
            timeout=120,
        )
        if not (p.stdout or "").strip():
            err = (p.stderr or "").strip()
            return {"error": err or f"imdb subprocess failed rc={p.returncode}", "best": None}
        obj = _safe_json_loads(p.stdout or "")
        if p.returncode != 0 and "error" not in obj:
            err = (p.stderr or "").strip()
            obj["error"] = err or f"imdb subprocess failed rc={p.returncode}"
        return obj

    def _suggest(self, title: str) -> list[dict[str, Any]]:
        t = (title or "").strip()
        if not t:
            return []
        first = t[0].lower()
        q = urllib.parse.quote(t)
        url = f"https://v2.sg.media-imdb.com/suggestion/{first}/{q}.json"
        obj = self._http_json(url)
        if not isinstance(obj, dict):
            return []
        d = obj.get("d")
        if not isinstance(d, list):
            return []
        out: list[dict[str, Any]] = []
        for it in d[:20]:
            if not isinstance(it, dict):
                continue
            imdb_id = str(it.get("id") or "")
            if not imdb_id.startswith("tt"):
                continue
            out.append({"imdb_id": imdb_id, "title": it.get("l"), "year": it.get("y"), "kind": it.get("q")})
        return out

    def _best_from_suggest(self, kind: str, title: str, year: int | None, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
        def norm(s: str) -> str:
            return "".join(ch.lower() for ch in s if ch.isalnum() or ch.isspace()).strip()

        want_kind = (kind or "").lower()
        want_title = norm(title or "")
        best: dict[str, Any] | None = None
        best_score = -10_000
        for c in candidates:
            c_title = norm(str(c.get("title") or ""))
            c_year = c.get("year")
            c_kind = str(c.get("kind") or "").lower()
            s = 0
            if want_title and want_title in c_title:
                s += 30
            if year and isinstance(c_year, int):
                s -= min(abs(c_year - year), 10) * 3
            if want_kind == "tv":
                if "tv" in c_kind:
                    s += 20
                else:
                    s -= 20
            else:
                if "tv" in c_kind:
                    s -= 10
            if s > best_score:
                best_score = s
                best = c
        return best

    def _http_json(self, url: str) -> Any:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = resp.read()
        except Exception:
            return None
        try:
            return json.loads(data.decode("utf-8", errors="replace"))
        except Exception:
            return None

    def _fetch_title(self, imdb_tt: str) -> dict[str, Any] | None:
        tt = (imdb_tt or "").strip().lower()
        if not tt.startswith("tt"):
            return None
        urls = [
            f"https://m.imdb.com/title/{tt}/",
            f"https://www.imdb.com/title/{tt}/",
        ]
        html = None
        for url in urls:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=20) as resp:
                    status = getattr(resp, "status", 200)
                    if status == 202:
                        continue
                    html = resp.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            if html:
                break
        if not html:
            return None
        obj = self._parse_ld_json(html)
        if obj is None:
            return None
        rating = None
        votes = None
        ag = obj.get("aggregateRating")
        if isinstance(ag, dict):
            rating = ag.get("ratingValue")
            votes = ag.get("ratingCount")
        year = None
        dp = obj.get("datePublished")
        if isinstance(dp, str) and len(dp) >= 4 and dp[:4].isdigit():
            year = int(dp[:4])
        kind = str(obj.get("@type") or "").lower()
        return {
            "imdb_id": tt[2:],
            "kind": kind,
            "title": obj.get("name"),
            "year": year,
            "rating": rating,
            "votes": votes,
            "canonical_title": obj.get("name"),
            "canonical_year": year,
            "series_title": obj.get("name") if kind == "tvseries" else None,
            "franchise_root": None,
        }

    def _parse_ld_json(self, html: str) -> dict[str, Any] | None:
        m = re.search(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', html, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            return None
        text = m.group(1).strip()
        if not text:
            return None
        try:
            obj = json.loads(text)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        return obj

    def _to_title(self, obj: dict[str, Any]) -> ImdbTitle:
        return ImdbTitle(
            imdb_id=_as_str(obj.get("imdb_id")) or "",
            kind=_as_str(obj.get("kind")) or "unknown",
            title=_as_str(obj.get("title")),
            year=_as_int(obj.get("year")),
            rating=_as_float(obj.get("rating")),
            votes=_as_int(obj.get("votes")),
            canonical_title=_as_str(obj.get("canonical_title")),
            canonical_year=_as_int(obj.get("canonical_year")),
            series_title=_as_str(obj.get("series_title")),
            franchise_root=_as_str(obj.get("franchise_root")),
        )
