#!/usr/bin/env python3
"""Meaning-and-life essay for a CRYPT track report.

After MusicBrainz/Wikipedia research, write a full essay: what the song is
about, and how a listener might carry that into ordinary life.
Uses SpaceXAI (xAI chat completions) when XAI_API_KEY is set.
Stdlib urllib only — DualLite cannot pip install SDKs.
"""
from __future__ import print_function

import json
import os
import re

try:
    from urllib.request import Request, urlopen
except ImportError:
    from urllib2 import Request, urlopen

from research import _clean, sentences

XAI_URL = os.environ.get("CRYPT_XAI_URL", "https://api.x.ai/v1/chat/completions")
XAI_MODEL = os.environ.get("CRYPT_ESSAY_MODEL", "grok-4.5")
CLIENT = "CRYPT/2.1.0 (https://github.com/GeorgieTech/GIGAWATT-V2)"


def _api_key():
    return (os.environ.get("XAI_API_KEY") or os.environ.get("CRYPT_XAI_KEY") or "").strip()


def paragraphs(text):
    text = str(text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    chunks = re.split(r"\n\s*\n", text)
    out = []
    for chunk in chunks:
        row = _clean(chunk)
        if row:
            out.append(row)
    if len(out) == 1 and len(out[0]) > 420:
        bits = re.split(r"(?<=[.!?])\s+", out[0])
        packed, buf = [], ""
        for sent in bits:
            if not sent:
                continue
            buf = (buf + " " + sent).strip() if buf else sent
            if len(buf) > 280:
                packed.append(buf)
                buf = ""
        if buf:
            packed.append(buf)
        return packed
    return out


def _wiki_body(page):
    page = page or {}
    return page.get("extract_long") or page.get("extract") or ""


def _theme_lines(text, limit=4):
    text = _clean(text)
    if not text:
        return []
    keys = (
        " about ", " theme", " meaning", " explores", " deals with",
        " tells ", " story of", " is a song", " written about", " reflects",
    )
    found = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        low = " " + sent.lower() + " "
        if any(k in low for k in keys):
            found.append(sent.strip())
        if len(found) >= limit:
            break
    if not found:
        return [sentences(text, 3)] if text else []
    return found


def fallback_essay(ctx):
    """Long sourced essay when no API key is set. Does not invent credits."""
    title = ctx.get("title") or "This track"
    artist = ctx.get("artist") or "the artist"
    album = ctx.get("album") or ""
    year = ctx.get("year") or ""
    genre = ctx.get("genre") or ""
    origin = ctx.get("origin") or ""
    wiki_song = _wiki_body(ctx.get("wiki_song"))
    wiki_artist = _wiki_body(ctx.get("wiki_artist"))
    lyrics = _clean(ctx.get("lyrics") or "")
    desc = _clean((ctx.get("wiki_song") or {}).get("description") or "")
    paras = []

    open_line = '"%s" is a recording by %s' % (title, artist)
    if album and album != "Unknown album":
        open_line += " from the album %s" % album
    if year:
        open_line += ", dated %s in the tags and public discography we could reach" % year
    if genre:
        open_line += ". The file is tagged %s" % genre
    open_line += "."
    paras.append(open_line)

    if wiki_artist:
        paras.append(
            "Who is speaking matters. " + sentences(wiki_artist, 4)
        )
    elif origin:
        paras.append(
            "%s is documented as coming out of %s. That background is part of how the record lands."
            % (artist, origin)
        )

    if wiki_song:
        paras.append(
            "What the public record says about the song and the project around it: "
            + sentences(wiki_song, 6)
        )
        themes = _theme_lines(wiki_song)
        if themes:
            paras.append(
                "On meaning, the sources do not replace sitting with the record, but they do name a direction: "
                + " ".join(themes)
            )
    elif desc:
        paras.append("Wikipedia files this work as %s." % desc)
    else:
        paras.append(
            "There is no long public write-up for this exact title in the pages we reached. "
            "The meaning then has to be read from the title, the album it sits on, the artist’s documented life, "
            "and — when we have them — the lyrics on disk."
        )

    if lyrics:
        snippet = lyrics
        if len(snippet) > 700:
            snippet = snippet[:700].rsplit(" ", 1)[0] + "…"
        paras.append(
            "The words on the recording, as stored next to the file, are part of the evidence, not decoration: "
            + snippet
        )

    paras.append(
        "How this can enter a life is quieter than a review. A song is not advice and it is not a substitute "
        "for a hard conversation. It is a room you can step into for three or four minutes and come out slightly "
        "rearranged. If the documented story is ambition, exile, grief, faith, swagger, or a concept-album journey, "
        "you can use “%s” as a marker for the hour you chose one of those on purpose."
        % title
    )
    paras.append(
        "Practically: play it when you need the feeling named. Play it in a car after a decision, on a walk when "
        "the day did not go as planned, or in a kitchen at night when you are trying to remember who you are when "
        "nobody is watching. If the lyric or the public write-up points at becoming someone, let the track be a "
        "check against shrinking. If it points at loss, let it sit with you without demanding a lesson. If it is "
        "simply a scene, a flex, or a world-build, it can still be a private flag — this is the sound of a moment "
        "you meant."
    )
    paras.append(
        "That is the whole job of a report like this: enough fact that the story is not invented, and enough "
        "human use that the fact is not dead. %s made “%s”. You get to decide what you do with the minutes it occupies."
        % (artist, title)
    )
    return paras


def _post_json(url, body, headers, timeout=55):
    raw = json.dumps(body).encode("utf-8")
    hdrs = dict(headers or {})
    hdrs["Content-Type"] = "application/json"
    hdrs["Content-Length"] = str(len(raw))
    req = Request(url, data=raw, headers=hdrs)
    fh = urlopen(req, timeout=timeout)
    try:
        blob = fh.read(400000)
    finally:
        fh.close()
    return json.loads(blob.decode("utf-8"))


def _choice_text(data):
    if not isinstance(data, dict):
        return ""
    if data.get("output_text"):
        return str(data.get("output_text") or "")
    choices = data.get("choices") or []
    if choices:
        msg = (choices[0] or {}).get("message") or {}
        return str(msg.get("content") or "")
    for item in data.get("output") or []:
        for chunk in (item or {}).get("content") or []:
            if (chunk or {}).get("text"):
                return str(chunk.get("text") or "")
    return ""


def _prompt(ctx):
    bits = [
        "Title: %s" % (ctx.get("title") or ""),
        "Artist: %s" % (ctx.get("artist") or ""),
        "Album: %s" % (ctx.get("album") or ""),
        "Year: %s" % (ctx.get("year") or ""),
        "Genre: %s" % (ctx.get("genre") or ""),
        "Origin: %s" % (ctx.get("origin") or ""),
        "Facts:",
    ]
    for fact in ctx.get("facts") or []:
        bits.append("- %s: %s" % (fact.get("label"), fact.get("value")))
    song = _wiki_body(ctx.get("wiki_song"))
    artist = _wiki_body(ctx.get("wiki_artist"))
    if song:
        bits.append("Wikipedia / song or album notes:")
        bits.append(song[:5000])
    if artist:
        bits.append("Wikipedia / artist notes:")
        bits.append(artist[:3500])
    if ctx.get("lyrics"):
        bits.append("Lyrics on disk (may be incomplete):")
        bits.append(str(ctx.get("lyrics") or "")[:2500])
    bits.append("Sources: " + "; ".join("%s <%s>" % (s.get("label"), s.get("url")) for s in (ctx.get("sources") or [])))
    return "\n".join(bits)


def xai_essay(ctx, post=None):
    key = _api_key()
    if not key:
        return None, "no key"
    body = {
        "model": XAI_MODEL,
        "temperature": 0.4,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You write long-form music notes for a private HiFi listening report. "
                    "Using ONLY the facts, Wikipedia notes, and lyrics supplied, write a full essay of 5 to 8 short paragraphs. "
                    "Cover: (1) what the song and its project are about — meaning, story, tone; "
                    "(2) how a listener might incorporate that meaning into ordinary life "
                    "(work, grief, ambition, love, faith, recovery, courage) as the sources actually support. "
                    "Do not invent credits, dates, chart positions, or plot points that are not in the sources. "
                    "If a line-by-line meaning is not documented, say so and interpret cautiously from title, album, artist life, and lyrics. "
                    "No hashtags. No bullet lists. No title heading. Plain paragraphs only."
                ),
            },
            {"role": "user", "content": _prompt(ctx)},
        ],
    }
    headers = {
        "Authorization": "Bearer " + key,
        "User-Agent": CLIENT,
    }
    sender = post or _post_json
    try:
        data = sender(XAI_URL, body, headers, 55)
    except Exception:
        return None, "request failed"
    text = _choice_text(data)
    paras = paragraphs(text)
    if len(paras) < 2:
        return None, "short"
    return paras, ""


def write_essay(ctx, writer=None):
    if writer:
        return writer(ctx)
    paras, err = xai_essay(ctx)
    if paras:
        return paras, "xai"
    return fallback_essay(ctx), "fallback" if err else "fallback"
