# Overview

PDFXML Tools turns a region of a PDF page into a DocBook 5 XML fragment
-- a `<para>`, `<itemizedlist>`, `<orderedlist>`, or `<informaltable>`
-- or into a PNG image. There is also a standalone tool for cropping an
image.

Nothing is stored: an uploaded PDF is processed and deleted a few
minutes after you stop working, and the image cropper runs entirely in
your browser.

## Limits

- One PDF is held per session; uploading a new one replaces it.
- Maximum upload size is 50 MB.
- If a page seems stuck, reload -- an idle upload is cleared
  automatically after about 20 minutes.
