# Faithful Image Capture Plan

## Goal

Image extraction must preserve every page element inside the selected region,
including PDF text, while removing only the `SurePoint Ag Systems` watermark.
The existing redaction flow is unsuitable because its geometric redaction can
delete body text crossed by the diagonal watermark.

## Approach

Add a non-destructive watermark-removal path used only by image extraction:

1. Copy the uploaded PDF to a temporary working document.
2. Inspect the selected page's `rawdict` text output.
3. Locate the line whose text is exactly `SurePoint Ag Systems` and verify its
   direction matches the known watermark rotation.
4. Locate the PDF content stream objects responsible for that rotated text.
5. Remove only the watermark text-showing operators from those streams.
6. Render the requested rectangle from the modified temporary document.
7. Apply the existing user-requested erase rectangles after watermark removal.
8. Delete the temporary document after rendering, including error paths.

The original PDF must remain untouched. Text, vector graphics, raster images,
and unrelated content streams must be copied byte-for-byte where possible.

## PDF Stream Editing

PyMuPDF should remain responsible for page inspection, geometry, rendering, and
sandbox execution. Use its low-level xref and stream APIs where practical. If
stream decoding, filtering, or object reconstruction becomes brittle, add
`pikepdf` or `qpdf` for PDF object and content-stream manipulation.

The stream editor must understand the relevant PDF text operators, including
`BT`/`ET`, text positioning, `Tj`, and `TJ`. It must account for encoded text
and watermark text split across multiple text-showing operators. Matching must
use both the exact watermark string and the known rotated text state; never
remove text based on a bounding rectangle alone.

If the watermark cannot be mapped unambiguously to a content-stream sequence,
fail the image extraction with a clear error rather than falling back to
destructive redaction. A configuration or internal diagnostic option may allow
rendering with the watermark retained for recovery, but it must not silently
delete intersecting page content.

## Integration Points

- Keep paragraph, list, and table extraction behavior unchanged.
- Change only the image-rendering path currently used by
  `app/blueprints/extract.py` and `app/pdfops.py`.
- Preserve the existing selected PDF-point rectangle and output PNG contract.
- Preserve user erase rectangles, applying them after the watermark has been
  removed from the temporary document.
- Keep all PDF manipulation inside the existing sandbox worker.

## Validation

Add focused tests covering:

- A synthetic page with rotated watermark text crossing ordinary body text:
  the output retains the body text and removes only the watermark.
- Watermark text split across multiple PDF text operators.
- Watermark text with a non-identity text matrix matching the known rotation.
- Pages without the watermark: image extraction succeeds unchanged.
- A watermark that cannot be uniquely mapped: extraction fails safely.
- Existing erase rectangles still remove only the requested areas.
- A real fixture derived from the sample case, with text above and below the
  diagram, verifying that the PNG contains the previously truncated text.
- Existing paragraph/list/table extraction and current crop UI tests.

For each fixture, compare extracted text before and after watermark removal.
The only permitted text difference is the exact watermark string. Also compare
rendered crops against expected dimensions and inspect pixels in regions where
the watermark crosses body text.

## Delivery Sequence

1. Add the stream-inspection and watermark-object identification helper.
2. Add a temporary-document stream rewrite with explicit ambiguity failures.
3. Route image rendering through the non-destructive path.
4. Add the synthetic and real-world regression fixtures.
5. Run focused extraction tests, then the complete test suite.
6. Remove the old image-path redaction call once the new tests prove it is no
   longer needed; retain any redaction helper still required by other flows.