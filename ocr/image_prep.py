"""
OpenCV helpers to find the driving license card in a photo, deskew it to a
standard rectangle, and crop out individual numbered-field regions.

Why this exists: the license layout is standardized (same fields in the same
place on every card), so once the card is deskewed to a known pixel size, a
numbered field's location is just a fixed rectangle — no per-photo guessing,
and OCR only has to read a small, clean crop instead of a whole photo with
background clutter.
"""

from __future__ import annotations

import cv2
import numpy as np

# Standard ID-1 card ratio (85.60mm x 53.98mm, ISO/IEC 7810) — used as the
# canonical pixel size we deskew every card photo to, so field regions
# (defined as fractions of width/height) line up regardless of the source
# photo's resolution or angle.
CARD_SIZE = (1011, 638)  # ~11.8 px/mm, arbitrary but sharp enough for OCR


def _order_corners(pts: np.ndarray) -> np.ndarray:
    """Orders 4 points as top-left, top-right, bottom-right, bottom-left —
    but "top-left" etc. here just means "whichever corner is nearest that
    corner of the *photo frame*" (smallest x+y sum, etc.). That labeling is
    purely geometric and has nothing to do with which corner is actually
    the card's own top-left in real life.

    That's fine as long as the card was photographed roughly upright
    (landscape, same way round as CARD_SIZE). It breaks when someone
    photographs the card rotated ~90° (e.g. holding their phone in
    portrait to fill the frame with a landscape card) — the "nearest to
    photo-frame-top-left" corner is then the card's real top-right, or
    bottom-left, etc., and every downstream fixed-fraction field region
    (FRONT_FIELD_REGIONS, BACK_CATEGORY_ROWS) ends up sampling the wrong
    part of the deskewed output.

    2026-08-27: confirmed this exact failure against a real photo (Rana
    Rayess's license, captured in portrait) — after the geometric labeling
    above, the resulting "width" (tl->tr) was 649.78px and "height"
    (tl->bl) was 914.84px, i.e. height > width, the opposite of an ID-1
    card's real aspect ratio (landscape, width > height — see
    _ID1_HEIGHT_OVER_WIDTH below, same constant already trusted elsewhere
    in this file for exactly this ratio). Verified empirically that
    rolling the 4 points by one position (np.roll(rect, -1, axis=0) —
    i.e. what we called "top-left" is actually the card's real
    bottom-left, and so on around) produces a correctly upright, landscape
    deskewed card: warped the same photo both ways and visually confirmed
    the rolled version matches the orientation of every other calibration
    photo used elsewhere in this codebase (header/flag top, fields 1-8
    left-aligned top-to-bottom, category grid and license number/blood
    type lower-right, signature area bottom) while the un-rolled version
    had all of that sideways.

    So: after the initial geometric labeling, if the resulting box is
    taller than it is wide, the card must have been captured rotated 90°
    from upright — correct it by rolling the corner assignment by one
    position before returning. This runs for every caller of
    find_card_corners (both the Canny-edge path and the
    _find_card_corners_by_color fallback), since both route through this
    function.
    """
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]

    width = float(np.linalg.norm(rect[1] - rect[0]))
    height = float(np.linalg.norm(rect[3] - rect[0]))
    if height > width:
        rect = np.roll(rect, -1, axis=0)

    return rect


# ISO/IEC 7810 ID-1 card ratio (height/width) — used by the color-based
# fallback below to correct a segmented card region's height, since the
# *bottom* edge of a color mask is often unreliable (a desk-surface shadow
# right at the card's edge blends into it) even when the top/left/right
# edges are accurate (real material change, not a lighting gradient).
_ID1_HEIGHT_OVER_WIDTH = 53.98 / 85.60

# An upper bound on how much of the photo frame a legitimate card quad can
# plausibly cover — added 2026-09-06 after a real photo (Richard Bou
# Tayeh's license, held up against a denim shirt) showed find_card_corners
# confidently accept a spurious near-full-frame quad instead of the actual
# card: the resulting "deskewed" output was visually indistinguishable
# from the raw photo itself, just resized to CARD_SIZE — background denim
# and all — meaning the "corners" it found were close to the photo's own
# 4 corners, not the card's. Root cause: a highly-textured, high-contrast
# background (denim weave) gives Canny edge detection plenty of false
# edges to assemble into a spurious "4-point" contour that easily clears
# the existing *lower* area bound (20%/15%) with nothing previously
# stopping an implausibly *large* one from passing too.
#
# Every real photo checked across this project so far — cards on a desk,
# held against a shirt, held over a car dashboard — shows a clear margin
# of background around the card, so a detected quad this close to the
# full frame is a much stronger signal that edge/color detection latched
# onto something other than the card than that the card genuinely fills
# the entire photo. Applied to both detection paths below (Canny-edge and
# color-based) for the same reason the lower bound already is: a
# real card region, however it's found, should look like a real card
# region. Deliberately generous (a card really can fill most of a
# close-up photo) — the goal is only to catch "nearly the whole frame,"
# not to second-guess a tight-but-plausible crop.
_MAX_PLAUSIBLE_CARD_AREA_FRACTION = 0.92


def _find_card_corners_by_color(image: np.ndarray) -> np.ndarray | None:
    """Fallback for when the background doesn't contrast enough for Canny
    edge detection to find a clean 4-sided outline — e.g. a card
    photographed on a wood desk, where the card's own pale color is close
    in tone to the desk. Segments the card by saturation (the card is much
    less saturated than a wood-grain background) and brightness (the card
    is usually better-lit than any shadowed desk around/under it) instead
    of edges, then corrects the segmented blob's height using the ID-1
    card's known physical aspect ratio rather than trusting its bottom
    edge directly — see _ID1_HEIGHT_OVER_WIDTH."""
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    sat, val = hsv[:, :, 1], hsv[:, :, 2]

    _, sat_mask = cv2.threshold(sat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    _, val_mask = cv2.threshold(val, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.bitwise_and(sat_mask, val_mask)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((15, 15), np.uint8))

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = image.shape[0] * image.shape[1]
    biggest = max(contours, key=cv2.contourArea)
    biggest_area = cv2.contourArea(biggest)
    if biggest_area < image_area * 0.15:
        return None  # too small to plausibly be the card
    if biggest_area > image_area * _MAX_PLAUSIBLE_CARD_AREA_FRACTION:
        return None  # too large to plausibly be just the card — see module note

    box = cv2.boxPoints(cv2.minAreaRect(biggest)).astype("float32")
    tl, tr, br, bl = _order_corners(box)

    width = float(np.linalg.norm(tr - tl))
    along = (tr - tl) / width
    perp = np.array([-along[1], along[0]], dtype="float32")
    if perp[1] < 0:  # ensure "perp" points down the image, toward the card's bottom
        perp = -perp
    height = width * _ID1_HEIGHT_OVER_WIDTH

    corrected_bl = tl + perp * height
    corrected_br = tr + perp * height
    return np.array([tl, tr, corrected_br, corrected_bl], dtype="float32")


def find_card_corners(image: np.ndarray) -> np.ndarray | None:
    """Finds the 4 corners of a rectangular card. Tries edge detection
    first (accurate when the background reasonably contrasts with the
    card), and falls back to color-based segmentation (see
    _find_card_corners_by_color) when that fails — e.g. a low-contrast
    wood-desk background, which edge detection alone cannot handle
    reliably. Returns an ordered (4, 2) float32 array, or None if neither
    approach found a confident card region.

    2026-09-06: both paths now also reject a candidate region that's
    implausibly LARGE (see _MAX_PLAUSIBLE_CARD_AREA_FRACTION), not just
    implausibly small — a highly-textured, high-contrast background (a
    denim shirt, confirmed on a real photo) can give Canny edge detection
    enough false edges to assemble a spurious "4-point" contour spanning
    nearly the whole frame, which used to sail through as if it were a
    real, if generously-cropped, card. Rejecting it here means the caller
    correctly sees this as a failed detection (falls through to the color
    path, or ultimately to deskew_failed=True) instead of confidently
    warping the wrong region and silently mislabeling every field read
    from it afterward."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 50, 150)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    image_area = image.shape[0] * image.shape[1]
    best = None
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        area = cv2.contourArea(c)
        if area < image_area * 0.2:
            continue  # too small to be the card itself
        if area > image_area * _MAX_PLAUSIBLE_CARD_AREA_FRACTION:
            continue  # too large to plausibly be just the card — see module note
        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * peri, True)
        if len(approx) == 4:
            best = approx.reshape(4, 2).astype("float32")
            break

    if best is not None:
        return _order_corners(best)

    return _find_card_corners_by_color(image)


def crop_region(image: np.ndarray, region: tuple[float, float, float, float]) -> np.ndarray:
    """Crops a region given as (x0, y0, x1, y1) fractions of image width/height."""
    h, w = image.shape[:2]
    x0, y0, x1, y1 = region
    return image[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]


def deskew_card(image: np.ndarray, output_size: tuple[int, int] = CARD_SIZE) -> np.ndarray | None:
    """Finds the card in `image` and warps it to a flat output_size
    rectangle. Returns None if the card corners couldn't be located
    confidently — caller should fall back to OCR-ing the raw photo (with a
    warning that accuracy will be lower) or ask the user to retake it."""
    corners = find_card_corners(image)
    if corners is None:
        return None

    w, h = output_size
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], dtype="float32")
    matrix = cv2.getPerspectiveTransform(corners, dst)
    return cv2.warpPerspective(image, matrix, (w, h))


# --- Fine alignment against a known-good reference photo -------------------
#
# 2026-08-30: deskew_card's 4-corner perspective warp gets every new photo to
# the same *size*, but "same size" isn't the same as "every printed field in
# exactly the same pixel position" — the 4 corners it warps from are found by
# fairly coarse edge/color detection, and a few pixels of corner error (a
# soft edge, slight motion blur, a shadow) becomes a real, if small,
# scale/rotation/translation error across the whole card. FRONT_FIELD_REGIONS
# and BACK_CATEGORY_ROWS were measured as fractions of ONE specific deskewed
# photo (Georges El Alam's), so they're only exactly right for a new photo
# that deskews to line up with that one, pixel for pixel — anything else is
# drift.
#
# Confirmed this drift is real, not just theoretical: a second real photo
# (Rana Rayess, 2026-08-30) that had already been correctly rotated and
# deskewed to the right card shape still had its "1"/"2" fields (surname/
# given name) read wrong — a value one field-row down from where it should
# have landed — while other fields on the same card read fine, i.e. a small
# few-percent misalignment, not a gross failure the rotation fix or a bad
# deskew would produce.
#
# align_to_reference corrects for this the same way document scanners and ID
# readers commonly do: match distinctive visual features (ORB keypoints —
# corners of letters, logo edges, table gridlines, the rosette pattern, all
# things a printed ID card has plenty of) between the new deskewed card and
# a saved reference photo of an already-correctly-read card, then solve for
# the homography that maps one onto the other and warp the new card through
# it. Every FRONT_FIELD_REGIONS/BACK_CATEGORY_ROWS fraction was measured
# against that same reference photo, so after this step they describe the
# same real pixels again, not just a same-sized rectangle — this is what
# makes the fixed fractions robust to "however the photo was taken" instead
# of only ever matching the one photo they were tuned against.
_ORB_FEATURE_COUNT = 2000
_MIN_GOOD_MATCHES = 15  # below this, there's not enough confident correspondence to trust a homography
_LOWE_RATIO_TEST = 0.75  # standard "is this match meaningfully better than the next-best" cutoff
_RANSAC_REPROJ_THRESHOLD_PX = 5.0


def align_to_reference(card_image: np.ndarray, reference_image: np.ndarray) -> np.ndarray:
    """Fine-aligns an already-deskewed card photo onto a reference photo of
    the same card layout (see module note above) using ORB feature matching
    + a RANSAC-fit homography. Returns `card_image` unchanged — never raises
    — if there isn't enough confident feature correspondence to trust an
    alignment (e.g. a blurry, glare-washed, or very low-detail photo): a
    bad homography would make every field region wrong in a new way, which
    is strictly worse than just keeping deskew_card's own output, so this
    only ever adds correction, never risk, on top of it."""
    gray_card = cv2.cvtColor(card_image, cv2.COLOR_BGR2GRAY)
    gray_ref = cv2.cvtColor(reference_image, cv2.COLOR_BGR2GRAY)

    orb = cv2.ORB_create(nfeatures=_ORB_FEATURE_COUNT)
    kp_card, des_card = orb.detectAndCompute(gray_card, None)
    kp_ref, des_ref = orb.detectAndCompute(gray_ref, None)
    if des_card is None or des_ref is None or len(kp_card) < _MIN_GOOD_MATCHES or len(kp_ref) < _MIN_GOOD_MATCHES:
        return card_image

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = matcher.knnMatch(des_card, des_ref, k=2)
    good_matches = [m for pair in raw_matches if len(pair) == 2
                     for m, n in [pair] if m.distance < _LOWE_RATIO_TEST * n.distance]
    if len(good_matches) < _MIN_GOOD_MATCHES:
        return card_image

    src_pts = np.float32([kp_card[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp_ref[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
    homography, inlier_mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, _RANSAC_REPROJ_THRESHOLD_PX)
    if homography is None or inlier_mask is None or int(inlier_mask.sum()) < _MIN_GOOD_MATCHES:
        return card_image

    h, w = reference_image.shape[:2]
    return cv2.warpPerspective(card_image, homography, (w, h))
