# assets/

Static, non-code files the app draws onto generated PDFs at runtime —
never OCR reference data (that lives under `ocr/reference_templates/`,
which is a different thing: real reference photos used to *read*
documents, not artwork used to *produce* one).

## laa_logo.png

Expected here by `printing/receipt_page.py` for the Cash Receipt template
(see that module's docstring) — the Lebanon Automobile Association seal
shown in the top-left corner of a real printed receipt (confirmed against
Georgio's 2026-09-26 video of LAA's own "View Receipt" screen). Not
included in this repo yet: Claude does not fabricate a real organization's
logo/seal from a blurry video frame, so this file is intentionally absent
until Georgio sends the actual image.

`render_receipt` in `printing/receipt_page.py` checks whether this file
exists before drawing it and simply skips the logo (text header only,
correctly positioned to still look right without it) if it's missing — so
the feature works today and the logo can be dropped in later with no code
change, just add `laa_logo.png` to this folder. A reasonably high-
resolution, roughly-square PNG (transparent background preferred) will
scale best; `render_receipt`'s `_LOGO_SIZE` constant controls the printed
size regardless of the source file's own pixel dimensions.

Remember to add any new file placed here to `packaging/idl_app.spec`'s
`datas` list too (see that file's existing `ocr/reference_templates`
entry for the pattern) — otherwise a packaged .exe build won't include it
even though it works fine running from source.
