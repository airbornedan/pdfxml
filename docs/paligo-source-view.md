# Paligo's "XML source" view — working notes

Shared, tracked scratchpad for reverse-engineering what Paligo's source
view actually is, so we can build a tool that tells an intern **why a
topic won't validate** and hands back a content-preserving fix.

Add findings here as we get them. Rough and incremental is fine — this
is the evidence log, not a spec.

---

## Why this file exists

- Paligo's WYSIWYG editor places the cursor unpredictably, so heavy edits
  routinely drop an element into an invalid spot (canonical case: a bare
  `<para>` directly inside `<orderedlist>` instead of inside a
  `<listitem>`). The topic then can't be saved.
- Paligo's validator reports this as a bare **"element not allowed here"**
  — no element name, no location. Useless.
- The "source" view is **not** real DocBook 5. It's a lossy serialization
  of Paligo's internal editor model. What its validator *accepts* is a
  third thing again (e.g. CALS tables are valid DocBook 5 but the source
  view rejects them — see the table-markup decision in the repo history).
- So we **cannot** just run the pasted XML through `schema/docbook.rng`
  (DocBook 5.2.1 RelaxNG, already wired into `docbook.validate_fragment`).
  It would flag things Paligo accepts and pass things Paligo rejects.
- Paligo's own "Automatically Fix Problematic Element Structures" silently
  **deletes** the content it can't place. Our tool must never do that.

## What we're trying to build

Phase 2 of the "Fix XML for Paligo" tool (`app/paligo.py`, `/normalize`):
paste the broken source-view XML → get back (a) which element is wrong
and **where** (line number), and (b) a corrected fragment when a
deterministic fixer applies and the result re-checks clean.

**Hard contract:** every fix is wrap / move / unwrap / split. 100% of
text preserved. Show a diff. Never delete. If it can't repair without
dropping content, say so and stop.

Approach: an **empirical, Paligo-specific model** — a hand-built
`{parent → allowed children}` + attribute/id ruleset for the ~40
elements the team actually uses, seeded from the findings below and
grown every time we hit a new case. Small and honest beats big and
wrong.

---

## Recon checklist

- [ ] Is external / Oxygen editing available on our Paligo plan? That
      integration ships the actual schema Paligo validates against — the
      grail. If yes, drop it in `schema/` next to `docbook.rng`.
- [ ] Network tab while opening the source view: is a `.rng` / `.xsd` /
      schema JSON fetched for the editor's own linting? Capture it.
- [ ] Does `Export → DocBook` ship a schema / catalog / Schematron in
      the bundle?
- [ ] Support ticket: what schema + version does source-view validation
      run against?
- [ ] REST API — ruled out as a repair channel (costs extra; the license
      tied to API calls can't use the editor concurrently; generally
      unusable). Note here if that changes.

---

## Findings

### Topic / root structure

_What does a topic's source view look like at the top? Root element
(`<section>`? `<topic>`?), required children (`<title>`?), version
attribute, namespace declaration, `xml:id` conventions._

- TBD

### Element vocabulary actually in use

_Pulled from ~a dozen real exported topics. The set the ruleset needs to
cover._

- TBD

### Content-model rules observed

_The growing `{parent → allowed children}` table. One row per parent as
we confirm it._

| Parent | Allowed children (observed) | Notes |
|--------|-----------------------------|-------|
| `orderedlist` / `itemizedlist` | `listitem` (+ `title`?) | a bare `<para>` here is the canonical break |
| `listitem` | `para`, nested lists, … | first child must be a block; bare text rejected? |
| _..._ | | |

### Fault-injection log

_Deliberately break a known-good topic, record what Paligo does._

| # | The break | Source-view XML (snippet) | Paligo's verbatim error | Actual cause | Correct fix | "Fix Problems" behavior |
|---|-----------|---------------------------|-------------------------|--------------|-------------|-------------------------|
| 1 | `<para>` moved directly under `<orderedlist>` | | | | wrap each stray `<para>` in `<listitem>` | |
| 2 | | | | | | |

### Paligo error string → real cause

_Paligo's messages are terse and reused. Map each one we see to what it
actually means._

| Paligo says | Really means | How to locate it |
|-------------|--------------|------------------|
| "element not allowed here" | some child violates its parent's content model | walk the tree against the ruleset above |
| _..._ | | |

### Schema / DTD artifacts found

_Anything we can get our hands on: the editor's linting schema, an
export-bundle schema, a version string. File paths where saved._

- TBD

### Namespace / PI / attribute quirks

_Does the source view use `xmlns`? Processing instructions for Paligo
metadata? Profiling attributes (`audience`, `os`, custom)? Whitespace
handling oddities?_

- TBD

### "Fix Problems" deletion behavior

_When Paligo's auto-fix deletes content — is it exactly the nodes it
can't place? A pattern here tells us what our tool must catch **first**
so nobody ever clicks that button._

- TBD

### Divergences from stock DocBook 5.2.1

_Where Paligo's accepted dialect differs from `schema/docbook.rng` —
things it rejects that the schema allows, and vice versa._

- CALS tables (`tgroup`/`row`/`entry`): valid DocBook 5, **rejected** by
  the source view. The Extract/Fix XML tools already emit the HTML table
  model (`informaltable` + `tr`/`th`/`td`, each cell `<para>`-wrapped)
  for this reason.
- TBD

---

## Real broken samples

_Drop sanitized `source-view.xml` + the Paligo error for each real
incident here (or under `docs/paligo-samples/`). The labelled corpus is
worth more than any schema._

- TBD
