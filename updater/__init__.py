"""
Auto-update: lets a machine running the built app (e.g. a company PC set
up via the USB walkthrough in README.md) pick up a new version over the
internet, without Georgio needing to physically visit it or redo the USB
transfer by hand.

Added 2026-09-11. See:
- updater/version.py -- the app's own version number and comparison logic.
- updater/onedrive.py -- fetches files from a OneDrive "anyone with the
  link" share, without embedding any Microsoft credential in the built
  app (same principle as never baking the Google Cloud credential into
  the .exe -- see packaging/idl_app.spec).
- updater/update_checker.py -- checks a small OneDrive-hosted
  version.json manifest for a version newer than the one running.
- updater/apply_update.py -- downloads, verifies, and installs an update,
  then relaunches the app.
- README.md's "Publishing an update" section -- how Georgio actually
  publishes a new version once this is wired up.

NOT YET VERIFIED end-to-end against a real OneDrive share or a real
Windows machine (this project is built from a Linux sandbox that can't
run the built .exe or reach a real OneDrive account -- see each module's
own docstring for exactly what IS covered by its tests). Treat the first
real update cycle as a real test, done deliberately on a machine that
isn't mid-production-use, before relying on this for a company PC.
"""
