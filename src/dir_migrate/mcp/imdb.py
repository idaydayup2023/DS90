from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
            return None, ImdbLookupDebug(status="not_found", error=None, candidates=tuple(out.get("candidates") or ()))
        if not isinstance(best, dict):
            return None, ImdbLookupDebug(status="error", error="imdb output best is not object", candidates=tuple(out.get("candidates") or ()))
        try:
            p.write_text(json.dumps(best, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return self._to_title(best), ImdbLookupDebug(status="ok", error=None, candidates=tuple(out.get("candidates") or ()))

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
