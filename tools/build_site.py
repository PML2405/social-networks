#!/usr/bin/env python3
"""Build the Social Networks study hub.

Reads the source PDFs (weekly transcripts + assignment solutions) and the
handwritten-notes HTML in notes/, and generates:

  1_Assignment_Solutions/  2_Transcripts/        PDFs (copied + renamed)
  text/notes|solutions|transcripts|weeks/        plain-text versions for AI chat tools
  index.html llms.txt manifest.json sitemap.xml robots.txt .nojekyll

Usage:  python3 tools/build_site.py --src "<folder with 01_Assignment_Solutions, 02_Transcripts_By_Week>"
Needs:  pip install pymupdf beautifulsoup4 lxml
"""
import argparse, html, json, os, re, shutil
from datetime import date
from pathlib import Path

import pymupdf
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

BASE = "https://pml2405.github.io/social-networks/"
REPO = "https://github.com/PML2405/social-networks"
COURSE = "Social Networks"
COURSE_LONG = "Social Networks (NPTEL, IIT Ropar, Prof. S. R. S. Iyengar)"

ROOT = Path(__file__).resolve().parent.parent


# ----------------------------------------------------------------- data
def load_lectures():
    out = []
    for line in (ROOT / "tools/data/lectures.psv").read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        w, n, title, p = line.split("|")
        out.append(dict(week=int(w), num=int(n), title=title, full_page=int(p) + 1))
    return out


def load_week_meta():
    """Week title + one-line blurb, parsed from the notes' series cover."""
    soup = BeautifulSoup((ROOT / "notes/index.html").read_text(), "lxml")
    meta = {}
    for li in soup.select(".toc-card li"):
        a = li.find("a")
        m = re.match(r"Week (\d+) [—-] (.*)", a.get_text(" ", strip=True))
        meta[int(m.group(1))] = dict(title=m.group(2).strip(),
                                     blurb=li.find("span").get_text(" ", strip=True))
    return meta


def human(n):
    return f"{n/1e6:.1f} MB" if n >= 1e6 else f"{round(n/1e3)} KB"


def squeeze(text):
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


# ----------------------------------------------------- HTML notes -> text
BLOCKS = {"p", "div", "section", "ul", "ol", "li", "table", "tr", "blockquote", "figure",
          "figcaption", "aside", "header", "footer", "dl", "dt", "dd", "details", "summary",
          "h1", "h2", "h3", "h4", "h5", "h6", "pre", "br"}


def notes_to_text(path):
    soup = BeautifulSoup(Path(path).read_text(), "lxml")
    for t in soup(["script", "style", "link", "meta", "head"]):
        t.decompose()
    for c in soup.find_all(string=lambda x: isinstance(x, Comment)):
        c.extract()
    for s in soup.select("svg.defs, svg.doodle, .margin-rule"):
        s.decompose()
    out, code = [], []

    def emit(s):
        out.append(s)

    def walk(node, in_pre=False):
        if isinstance(node, NavigableString):
            s = str(node)
            emit(s if in_pre else re.sub(r"\s+", " ", s))
            return
        if not isinstance(node, Tag):
            return
        name = node.name
        if name == "svg":
            texts = [re.sub(r"\s+", " ", t.get_text(" ", strip=True)) for t in node.find_all("text")]
            texts = [t for t in texts if t]
            if texts:
                emit("\n[diagram: " + " | ".join(texts) + "]\n")
            return
        if name == "table":
            emit("\n")
            for tr in node.find_all("tr"):
                cells = [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["th", "td"])]
                emit("| " + " | ".join(cells) + " |\n")
            emit("\n")
            return
        if name == "pre":
            code.append("```\n" + node.get_text().strip("\n") + "\n```")
            emit(f"\n@@CODE{len(code) - 1}@@\n")
            return
        if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(name[1])
            emit("\n\n" + "#" * level + " ")
            for c in node.children:
                walk(c)
            emit("\n\n")
            return
        if name == "li":
            emit("\n- ")
            for c in node.children:
                walk(c, in_pre)
            emit("\n")
            return
        if name == "code":
            emit("`" + node.get_text() + "`")
            return
        if name in ("b", "strong"):
            emit("**")
            for c in node.children:
                walk(c, in_pre)
            emit("**")
            return
        blk = name in BLOCKS
        if blk:
            emit("\n")
        for c in node.children:
            walk(c, in_pre)
        if blk:
            emit("\n")

    walk(soup.body)
    text = "".join(out)
    text = html.unescape(text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r"\*\* \*\*", " ", text)
    text = re.sub(r"\n\n(?=- )", "\n", text)  # keep list items tight
    text = re.sub(r"@@CODE(\d+)@@", lambda m: code[int(m.group(1))], text)  # restore code verbatim
    return squeeze(text)


# ------------------------------------------------------ PDF -> text
def pdf_pages(path):
    with pymupdf.open(path) as d:
        return [p.get_text() for p in d], len(d)


def transcript_text(path, lectures, week):
    """Transcript PDF (page 1 = generated cover) -> text with lecture + page markers."""
    pages, n = pdf_pages(path)
    first_full = lectures[0]["full_page"]
    starts = {l["full_page"] - first_full + 2: l for l in lectures}  # local page number -> lecture
    out = []
    for i, raw in enumerate(pages, 1):
        if i == 1:
            continue  # cover page = index only
        if i in starts:
            l = starts[i]
            out.append(f"\n\n=== LECTURE {l['num']}: {l['title']} (Week {week}, transcript PDF page {i}) ===\n")
        t = raw.replace("­", "")
        t = re.sub(r"[ \t]+\n", "\n", t)
        t = re.sub(r"\s*\n\s*(?=\(Refer Slide Time)", "\n\n", t)  # slide markers start a new paragraph
        t = re.sub(r"(?<!\n)\n(?!\n)", " ", t)                    # un-wrap hard line breaks
        t = re.sub(r" {2,}", " ", t).strip()
        t = re.sub(rf"\s*\b{first_full + i - 3}$", "", t)  # drop the printed source page number
        out.append(f"[p.{i}] {t}\n")
    return squeeze("\n".join(out)), n


def solution_text(path):
    pages, n = pdf_pages(path)
    out = []
    for i, raw in enumerate(pages, 1):
        t = re.sub(r"[ \t]+\n", "\n", raw).replace("­", "")
        out.append(f"[p.{i}]\n{t.strip()}\n")
    return squeeze("\n".join(out)), n


# ------------------------------------------------------------- build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    args = ap.parse_args()
    src = Path(args.src)

    lectures = load_lectures()
    meta = load_week_meta()
    today = date.today().isoformat()
    weeks = []

    for w in range(1, 13):
        nn = f"{w:02d}"
        lec = [l for l in lectures if l["week"] == w]
        rng = f"Lec{lec[0]['num']:02d}-{lec[-1]['num']:02d}"
        info = dict(week=w, nn=nn, title=meta[w]["title"], blurb=meta[w]["blurb"],
                    lec_first=lec[0]["num"], lec_last=lec[-1]["num"])

        # --- PDFs
        sol_src = src / "01_Assignment_Solutions" / f"SocialNetworks_Week{nn}_Assignment_Solution.pdf"
        tr_src = src / "02_Transcripts_By_Week" / f"SocialNetworks_Week{nn}_Transcript.pdf"
        sol_name = f"Week_{nn}_Assignment_Solution.pdf"
        tr_name = f"Week_{nn}_Transcript_{rng}.pdf"
        shutil.copy2(sol_src, ROOT / "1_Assignment_Solutions" / sol_name)
        shutil.copy2(tr_src, ROOT / "2_Transcripts" / tr_name)

        # --- text
        notes_txt = notes_to_text(ROOT / f"notes/week-{nn}.html")
        sol_txt, sol_pp = solution_text(sol_src)
        tr_txt, tr_pp = transcript_text(tr_src, lec, w)
        (ROOT / f"text/notes/week-{nn}.txt").write_text(notes_txt)
        (ROOT / f"text/solutions/Week_{nn}_Assignment_Solution.txt").write_text(sol_txt)
        tr_txt_name = f"Week_{nn}_Transcript_{rng}.txt"
        (ROOT / f"text/transcripts/{tr_txt_name}").write_text(tr_txt)

        header = (f"# {COURSE_LONG}\n# Week {w}: {info['title']}\n"
                  f"# Lectures {info['lec_first']}-{info['lec_last']}\n"
                  f"# Website: {BASE}   Repo: {REPO}\n")
        combined = (
            header + "\n"
            "This file has three parts, in order: (A) the student's handwritten-style study NOTES, "
            "(B) the weekly ASSIGNMENT / question paper with solutions, (C) the full lecture TRANSCRIPTS. "
            "The notes are a condensed re-teach of the lectures; the transcript is the authority.\n\n"
            f"{'='*78}\nPART A - STUDY NOTES (Week {w})\n{'='*78}\n\n{notes_txt}\n"
            f"{'='*78}\nPART B - ASSIGNMENT & SOLUTIONS (Week {w})\n{'='*78}\n\n{sol_txt}\n"
            f"{'='*78}\nPART C - LECTURE TRANSCRIPTS (Week {w}, Lectures {info['lec_first']}-{info['lec_last']})\n{'='*78}\n{tr_txt}"
        )
        (ROOT / f"text/weeks/week-{nn}.txt").write_text(combined)

        def f(rel):
            return dict(path=rel, bytes=(ROOT / rel).stat().st_size)

        info.update(
            lectures=[dict(num=l["num"], title=l["title"],
                           page=l["full_page"] - lec[0]["full_page"] + 2) for l in lec],
            files=dict(
                notes_html=f(f"notes/week-{nn}.html"), notes_text=f(f"text/notes/week-{nn}.txt"),
                solution_pdf=dict(**f(f"1_Assignment_Solutions/{sol_name}"), pages=sol_pp),
                solution_text=f(f"text/solutions/Week_{nn}_Assignment_Solution.txt"),
                transcript_pdf=dict(**f(f"2_Transcripts/{tr_name}"), pages=tr_pp),
                transcript_text=f(f"text/transcripts/{tr_txt_name}"),
                week_text=f(f"text/weeks/week-{nn}.txt"),
            ))
        weeks.append(info)
        print(f"week {w}: notes {len(notes_txt)//1000}k  sol {len(sol_txt)//1000}k  transcript {len(tr_txt)//1000}k chars")

    parts = [f"# {COURSE_LONG} - all study notes (Weeks 1-12)\n# Website: {BASE}\n"]
    for w in weeks:
        parts.append(f"\n{'='*78}\nWEEK {w['week']}: {w['title']}\n{'='*78}\n\n" + (ROOT / w["files"]["notes_text"]["path"]).read_text())
    (ROOT / "text/all-notes.txt").write_text("\n".join(parts))

    write_index(weeks)
    write_llms(weeks)
    write_manifest(weeks, today)
    write_sitemap(weeks, today)
    (ROOT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {BASE}sitemap.xml\n")
    (ROOT / ".nojekyll").write_text("")


# ---------------------------------------------------------- outputs
def write_llms(weeks):
    L = [f"# {COURSE} - study material\n",
         f"> {COURSE_LONG}. All 12 weeks (166 lectures): hand-made study notes, assignment/question papers "
         "with solutions, and full lecture transcripts. Every item is available as plain text (best for AI "
         "chat) and as the original PDF/HTML. Notes are a condensed re-teach; the transcript is the authority.\n",
         f"Website: {BASE}", f"Repository: {REPO}",
         f"All notes in one file: {BASE}text/all-notes.txt\n", "---\n"]
    for w in weeks:
        f = w["files"]
        L.append(f"## Week {w['week']}: {w['title']}")
        L.append("Lectures: " + "; ".join(f"{l['num']} {l['title']} (transcript p. {l['page']})" for l in w["lectures"]))
        L.append(f"- [Week {w['week']}: everything as one text file (notes + assignment + transcript)]({BASE}{f['week_text']['path']}) ({human(f['week_text']['bytes'])})")
        L.append(f"- Study notes: [text]({BASE}{f['notes_text']['path']}) | [HTML]({BASE}{f['notes_html']['path']})")
        L.append(f"- Assignment solution: [text]({BASE}{f['solution_text']['path']}) | [PDF]({BASE}{f['solution_pdf']['path']}) ({f['solution_pdf']['pages']} pp, {human(f['solution_pdf']['bytes'])})")
        L.append(f"- Lecture transcript, Lectures {w['lec_first']}-{w['lec_last']}: [text]({BASE}{f['transcript_text']['path']}) | [PDF]({BASE}{f['transcript_pdf']['path']}) ({f['transcript_pdf']['pages']} pp, {human(f['transcript_pdf']['bytes'])})")
        L.append("")
    (ROOT / "llms.txt").write_text("\n".join(L))


def write_manifest(weeks, today):
    (ROOT / "manifest.json").write_text(json.dumps(dict(
        course=COURSE_LONG, base_url=BASE, repo=REPO, generated=today,
        all_notes=dict(path="text/all-notes.txt", bytes=(ROOT / "text/all-notes.txt").stat().st_size),
        weeks=weeks), indent=1, ensure_ascii=False))


def write_sitemap(weeks, today):
    urls = [BASE, BASE + "llms.txt", BASE + "manifest.json", BASE + "notes/index.html", BASE + "text/all-notes.txt"]
    for w in weeks:
        for k, v in w["files"].items():
            if not k.endswith("pdf"):
                urls.append(BASE + v["path"])
    body = "\n".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>" for u in urls)
    (ROOT / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + body + "\n</urlset>\n")


def write_index(weeks):
    total_pdf = sum(w["files"][k]["bytes"] for w in weeks for k in ("solution_pdf", "transcript_pdf"))
    n_lec = sum(len(w["lectures"]) for w in weeks)
    sections = []
    for w in weeks:
        f = w["files"]; nn = w["nn"]
        lecs = "".join(
            f'<li><a href="{f["transcript_pdf"]["path"]}#page={l["page"]}">Lecture {l["num"]}: {html.escape(l["title"])}</a></li>'
            for l in w["lectures"])
        sections.append(f"""
<section class="week" id="week-{w['week']}" data-text="{html.escape((w['title'] + ' ' + w['blurb'] + ' ' + ' '.join(l['title'] for l in w['lectures'])).lower())}">
  <h2>Week {w['week']} <span>{html.escape(w['title'])}</span></h2>
  <p class="blurb">{html.escape(w['blurb'])} &middot; Lectures {w['lec_first']}&ndash;{w['lec_last']}</p>
  <p class="all"><a href="{f['week_text']['path']}">All of week {w['week']} as one text file</a> <small>(notes + assignment + transcript, {human(f['week_text']['bytes'])})</small></p>
  <ul class="items">
    <li data-kind="notes"><b>Study notes</b> <a href="{f['notes_text']['path']}">Text</a> &middot; <a href="{f['notes_html']['path']}">Notebook page</a></li>
    <li data-kind="solutions"><b>Assignment solution</b> <a href="{f['solution_text']['path']}">Text</a> &middot; <a href="{f['solution_pdf']['path']}">PDF</a> <small>({f['solution_pdf']['pages']} pp, {human(f['solution_pdf']['bytes'])})</small></li>
    <li data-kind="transcripts"><b>Transcript, Lectures {w['lec_first']}&ndash;{w['lec_last']}</b> <a href="{f['transcript_text']['path']}">Text</a> &middot; <a href="{f['transcript_pdf']['path']}">PDF</a> <small>({f['transcript_pdf']['pages']} pp, {human(f['transcript_pdf']['bytes'])})</small></li>
  </ul>
  <details><summary>{len(w['lectures'])} lectures</summary><ul class="lecs">{lecs}</ul></details>
</section>""")

    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Social Networks Study Hub (NPTEL, IIT Ropar)</title>
<meta name="description" content="Social Networks (NPTEL, IIT Ropar): study notes, assignment solutions and full lecture transcripts for all 12 weeks, as plain text and PDF. Paste the link into ChatGPT or Claude to ask doubts.">
<link rel="alternate" type="text/plain" href="llms.txt" title="llms.txt">
<style>
:root{{--bg:#FBF7EC;--card:#fff;--ink:#2E2A3D;--soft:#5b5678;--line:#E2D9C4;--accent:#d9573a;--link:#2a5db0}}
@media (prefers-color-scheme:dark){{:root{{--bg:#1b1a22;--card:#24232d;--ink:#ece9f5;--soft:#a9a4c2;--line:#3a3850;--accent:#ff8a6b;--link:#8fb4ff}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
main{{max-width:880px;margin:0 auto;padding:24px 16px 80px}}
a{{color:var(--link)}}
header h1{{font-size:2rem;margin:.2em 0 0}} header p{{color:var(--soft);margin:.3em 0}}
.kicker{{letter-spacing:.12em;font-size:.8rem;color:var(--accent);font-weight:700}}
.how{{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:8px;padding:12px 16px;margin:18px 0}}
.how code{{background:var(--bg);padding:1px 6px;border-radius:4px;word-break:break-all}}
.bar{{position:sticky;top:0;background:var(--bg);padding:10px 0;z-index:5;display:flex;gap:8px;flex-wrap:wrap;border-bottom:1px solid var(--line)}}
.bar input{{flex:1 1 220px;padding:8px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--ink);font:inherit}}
.bar button{{padding:7px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--ink);cursor:pointer;font:inherit}}
.bar button[aria-pressed=true]{{background:var(--accent);color:#fff;border-color:var(--accent)}}
.week{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:14px 0}}
.week h2{{margin:0;font-size:1.25rem}} .week h2 span{{font-weight:500;color:var(--soft)}}
.blurb{{color:var(--soft);margin:.2em 0 .6em;font-size:.92rem}}
.items{{list-style:none;padding:0;margin:.4em 0}} .items li{{padding:4px 0}}
.items.hide-notes [data-kind=notes],.items.hide-solutions [data-kind=solutions],.items.hide-transcripts [data-kind=transcripts]{{display:none}}
small{{color:var(--soft)}} summary{{cursor:pointer;color:var(--soft)}} .lecs{{columns:2;font-size:.9rem}}
@media(max-width:620px){{.lecs{{columns:1}}}}
footer{{margin-top:30px;color:var(--soft);font-size:.9rem}}
</style>
</head>
<body>
<main>
<header>
  <div class="kicker">NPTEL ONLINE COURSE &middot; IIT ROPAR</div>
  <h1>Social Networks Study Hub</h1>
  <p>Prof. S. R. S. Iyengar &middot; 12 weeks, {n_lec} lectures, with <b>handwritten-style study notes</b>, assignment solutions and full lecture transcripts &middot; {len(weeks)*2} PDFs ({human(total_pdf)}).</p>
</header>

<div class="how">
  <b>Using this with ChatGPT / Claude:</b> paste this site link, or one week's text link, into the chat and ask your doubt.
  Everything is plain text, no files to upload. For one week (notes + assignment + transcript together):
  <br><code>{BASE}text/weeks/week-05.txt</code>
  <br>For only the condensed notes of the whole course: <a href="text/all-notes.txt">all notes as one text file</a>.
  Index for AI tools: <a href="llms.txt">llms.txt</a>.
  <br><small>Text is extracted from PDFs and may have small errors; the PDF is the authority. The notes are a condensed re-teach of the lectures.</small>
</div>

<div class="bar">
  <input id="q" type="search" placeholder="Search topics, e.g. PageRank, homophily, SIR" aria-label="Search weeks">
  <button data-f="all" aria-pressed="true">All</button>
  <button data-f="notes" aria-pressed="false">Notes</button>
  <button data-f="transcripts" aria-pressed="false">Transcripts</button>
  <button data-f="solutions" aria-pressed="false">Assignment solutions</button>
</div>

{''.join(sections)}

<footer>
  <a href="{REPO}">GitHub repository</a> &middot; <a href="manifest.json">manifest.json</a> &middot; <a href="sitemap.xml">sitemap.xml</a> &middot; <a href="notes/index.html">Notebook-style notes index</a>
  <p>Lecture numbers follow the NPTEL transcript (1&ndash;166).</p>
</footer>
</main>
<script>
(function(){{
  var weeks=[].slice.call(document.querySelectorAll('.week')),q=document.getElementById('q'),btns=[].slice.call(document.querySelectorAll('.bar button'));
  var kind='all';
  function apply(){{
    var s=q.value.trim().toLowerCase();
    weeks.forEach(function(w){{
      w.hidden = s && w.getAttribute('data-text').indexOf(s)<0;
      var ul=w.querySelector('.items');
      ul.className='items'+(kind==='all'?'':' hide-'+['notes','solutions','transcripts'].filter(function(k){{return k!==kind}}).join(' hide-'));
    }});
  }}
  q.addEventListener('input',apply);
  btns.forEach(function(b){{b.addEventListener('click',function(){{kind=b.getAttribute('data-f');btns.forEach(function(x){{x.setAttribute('aria-pressed',x===b)}});apply();}});}});
}})();
</script>
</body>
</html>
"""
    (ROOT / "index.html").write_text(page)


if __name__ == "__main__":
    main()
