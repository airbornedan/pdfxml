# content/

Source text for the in-app Markdown pages. Plain Markdown, edited here
and committed -- there is no in-app editor.

## Layout

```
content/
  process/          -> /process on the TRUSTED profile (SurePoint / Paligo)
  troubleshooting/  -> /troubleshooting (trusted profile only)
  process-public/   -> /process on the PUBLIC profile (generic guide)
  legal/            -> /terms and /privacy (public profile only)
```

The profile is `PDFXML_TRUSTED_NETWORK` (see `../pdfxml.md`). `process/`
and `process-public/` are the same page (`/process`) with different
content per deployment.

One `.md` file per tab, per page directory:

- **Order** is the sorted filename -- `NN-slug.md` (`10-`, `20-`, ...).
- **Label** is the first line, a single `# Heading`; it's not repeated
  in the body, so start body headings at `##`.

A missing or empty directory renders as one empty tab named after the page.

## Markdown notes

- [mistune](https://mistune.lepture.com/) + `table` plugin. Raw HTML is
  escaped -- `<product>` / `</section>` in prose render literally.
- Standard Markdown: `**bold**`, `` `code` ``, `1.` / `-` lists (4-space
  indent to nest), `>` quotes, ``` ``` ``` fences, pipe tables.
- Hard line break in a list item: two trailing spaces, or indent the
  continuation under the item text.
