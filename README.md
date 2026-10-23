# Social Networks (NPTEL) study hub

Notes, assignment solutions and full lecture transcripts for all 12 weeks of
*Social Networks* (NPTEL, IIT Ropar, Prof. S. R. S. Iyengar), published as a static site
that ChatGPT / Claude can read from a link.

**Site:** https://pml2405.github.io/social-networks/

Paste the site link (or one week's text link, e.g. `text/weeks/week-05.txt`) into an AI chat and ask your doubts.

```
index.html            study hub (all weeks, search)
llms.txt              plain-text index for AI tools   (also manifest.json, sitemap.xml)
notes/                handwritten-style notebook pages (HTML), one per week
1_Assignment_Solutions/  weekly question papers with solutions (PDF)
2_Transcripts/        weekly lecture transcripts (PDF, lecture index on page 1)
text/notes|solutions|transcripts/   plain-text versions of each item
text/weeks/           one file per week: notes + assignment + transcript
text/all-notes.txt    all 12 weeks of notes in one file
notes-kit/            kit used to author the notes
tools/build_site.py   regenerates everything except notes/ from the source PDFs
```

Rebuild: `pip install pymupdf beautifulsoup4 lxml` then
`python3 tools/build_site.py --src "<folder with 01_Assignment_Solutions and 02_Transcripts_By_Week>"`.
