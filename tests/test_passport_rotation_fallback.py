"""
Regression tests for whole-photo-rotation handling in extract_passport_data
-- see ocr/passport_ocr.py's module docstring, _looks_rotated_90,
_bio_orientation_looks_correct, and _resolve_bio_words.

This mechanism went through three real-photo-driven passes in one day
(2026-09-06), each corrected by pulling the next real photo's actual OCR
word dump rather than guessing:

1. Photo #8 (Richard Bou Tayeh) was rotated ~90 degrees from upright.
   First fix attempt: probe for the MRZ itself at 90/180/270 degrees when
   the existing 0-degree MRZ tiers both failed. On a real retest this did
   nothing, because Google Vision already read the MRZ correctly even on
   the sideways photo -- the existing whole-photo-at-0-degrees tier
   succeeded on its own, so the new rotation-probing tier never ran at all.
   (Still kept below as TryLocateMrzWithRotationTest/MrzChecksumTest --
   valid defense in depth for a hypothetical future photo whose MRZ Vision
   genuinely can't read sideways, even though this one's was fine.)

2. Realizing the real bug was BIO_SEARCH_REGION's fixed-fraction CROP
   sampling the wrong pixels of a still-sideways photo (regardless of how
   well Vision reads whatever lands in it), the second fix added
   _resolve_bio_words: retry the bio crop at 90-degree rotations if the
   original doesn't contain the bio page's "Republic of Lebanon" header
   line. This was ALSO not the right fix, confirmed on a ninth real photo.

3. Photo #9 (Charbel Sfeir), also rotated ~90 degrees, showed the header-
   keyword check itself was unreliable two ways: this photo's header word
   read as "ublic" (BIO_SEARCH_REGION's crop boundary clipped the leading
   "Rep" at this photo's specific framing, not a misread), so the correct
   rotation's own crop never matched "republic" at all; and separately,
   Vision reads "Lebanon"/"Libanaise" as clean words in EVERY orientation
   tried, including the still-sideways original, so a keyword being found
   was never proof the crop was right-side up to begin with. The real,
   current fix drops keyword-matching from this decision entirely and uses
   two purely geometric checks instead: _looks_rotated_90 (word boxes no
   longer tall-narrow) to pick a 90-degree rotation, and
   _bio_orientation_looks_correct ("First name"/"Father name"/
   "Nationality"/"Place of birth" appear in that real, consistently-observed
   top-to-bottom order) to tell the correct 90-degree direction apart from
   the upside-down one -- since rotating an already-sideways photo EITHER
   direction produces equally normal-looking (wide, short) word boxes, but
   only one direction is actually right-side up.

REAL_SFEIR_* below are exact word dumps from Charbel Sfeir's real photo
(2026-09-06, debug run 20260906_232639) at three orientations: the original
(sideways) crop, and both 90-degree rotation candidates -- pulled directly
from the device after that fix attempt's own on-device retest, specifically
because it showed the mechanism CHOOSING BETWEEN two candidates that both
"look plausible" is the part that actually needed real evidence, not just
"a rotated photo exists at all" (which photo #8's fixture already covered).
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ocr.image_prep import crop_region
from ocr.mrz_parser import parse_td3
from ocr.ocr_client import OcrResult, OcrWord
from ocr.passport_field_regions import BIO_SEARCH_REGION
from ocr.passport_ocr import (
    _bio_orientation_looks_correct,
    _crop_mrz_band,
    _looks_rotated_90,
    _resolve_bio_words,
    _try_locate_mrz_with_rotation,
    extract_passport_data,
)

# Real MRZ lines, transcribed directly from Richard Bou Tayeh's real
# passport photo (2026-09-06, debug run 20260906_213312) once read the
# right way up.
_REAL_LINE1 = "P<LBNBOU<TAYEH<<RICHARD<<<<<<<<<<<<<<<<<<<<"
_REAL_LINE2 = "LR24109358LBN7102187M3111079100173895 5<<16"
_REAL_MRZ_TEXT = _REAL_LINE1 + "\n" + _REAL_LINE2

# Same aspect ratio as Richard Bou Tayeh's real photo (a portrait-oriented
# 1280x960 frame, confirmed via cv2.imread on the real passport_00_full_photo.png).
_REAL_PHOTO_HEIGHT = 1280
_REAL_PHOTO_WIDTH = 960


def _w(text, x0, y0, x1, y1, conf):
    return OcrWord(text=text, confidence=conf, box=(x0, y0, x1, y1))


def _make_image(h, w):
    return np.zeros((h, w, 3), dtype="uint8")


# Exact real data from Richard Bou Tayeh's photo (run 20260906_213312),
# read from the ORIGINAL, physically-sideways orientation's BIO_SEARCH_REGION
# crop -- every word's box is narrow-and-tall, the signature _looks_rotated_90
# looks for.
REAL_ROTATED_BIO_WORDS = [
    _w("of", 121, 777, 147, 801, 0.993),
    _w("RICHARD", 298, 566, 316, 657, 0.992),
    _w("MILAD", 363, 594, 382, 660, 0.992),
    _w("Name", 188, 611, 199, 652, 0.991),
    _w("Place", 431, 615, 446, 661, 0.991),
    _w("RICHARD", 621, 409, 656, 569, 0.99),
    _w("of", 431, 595, 445, 613, 0.99),
    _w("109358LBN7102187M31110791001738955", 665, 49, 715, 868, 0.989),
    _w("2031", 547, 534, 566, 592, 0.989),
    _w("2021", 502, 534, 521, 592, 0.989),
    _w("TAYEH", 626, 622, 660, 740, 0.988),
    _w("LR2410935", 179, 226, 196, 339, 0.988),
    _w("name", 255, 575, 266, 618, 0.988),
    _w("NBOU", 630, 765, 663, 864, 0.988),
    _w("TAYEH", 230, 545, 245, 608, 0.987),
    _w("18", 408, 373, 424, 399, 0.987),
    _w("BOU", 230, 616, 246, 655, 0.986),
    _w("1971", 408, 276, 424, 331, 0.985),
    _w("Lebanon", 121, 669, 147, 771, 0.985),
    _w("Libanaise", 121, 388, 147, 501, 0.982),
    _w("LBN", 163, 498, 178, 530, 0.981),
    _w("Code", 148, 499, 159, 531, 0.979),
    _w("Date", 381, 392, 402, 430, 0.979),
    _w("République", 121, 511, 147, 643, 0.973),
    _w("02", 408, 339, 424, 365, 0.97),
    _w("11", 504, 599, 521, 627, 0.968),
    _w("/", 121, 648, 147, 663, 0.967),
    _w("08", 504, 637, 522, 664, 0.964),
    _w("of", 383, 373, 402, 387, 0.959),
    _w("birth", 431, 556, 445, 591, 0.949),
    _w("Passport", 156, 311, 183, 380, 0.944),
    _w("/", 121, 366, 147, 382, 0.942),
    _w("<<", 626, 572, 657, 619, 0.939),
    _w("date", 524, 574, 547, 611, 0.939),
    _w("LEBANESE", 404, 554, 431, 661, 0.938),
    _w("<", 629, 739, 660, 766, 0.938),
    _w("Public", 121, 808, 148, 869, 0.935),
    _w("First", 255, 621, 266, 655, 0.913),
    _w("Expiry", 525, 616, 548, 662, 0.91),
    _w("Nationality", 386, 575, 404, 660, 0.901),
    _w("HELALIE", 452, 575, 478, 663, 0.9),
    _w("07/11", 548, 599, 567, 666, 0.892),
    _w("/", 255, 562, 266, 577, 0.88),
    _w("RL", 157, 383, 184, 423, 0.866),
    _w("/", 387, 562, 403, 573, 0.863),
    _w("birth", 383, 333, 403, 368, 0.86),
    _w("Major", 478, 190, 493, 237, 0.858),
    _w("<<", 664, 0, 698, 51, 0.843),
    _w("N", 156, 299, 182, 312, 0.811),
    _w("<<", 620, 363, 652, 408, 0.778),
    _w("-", 665, 0, 697, 11, 0.763),
    _w("date", 481, 552, 504, 588, 0.748),
    _w("X90664", 178, 64, 194, 143, 0.737),
    _w("/", 482, 538, 504, 548, 0.716),
    _w("/", 525, 560, 546, 572, 0.655),
    _w("Authority", 478, 342, 502, 416, 0.647),
    _w("/", 478, 329, 500, 341, 0.634),
    _w("Assuance", 482, 592, 506, 662, 0.616),
    _w("Co", 478, 166, 492, 188, 0.467),
    _w("Das", 502, 388, 522, 422, 0.404),
    _w("-", 121, 118, 147, 130, 0.402),
]

# Exact real data from Charbel Sfeir's photo (2026-09-06, run
# 20260906_232639) at three orientations. The original crop is also
# sideways (tall-narrow boxes); the two 90-degree rotations both produce
# normal-looking (wide-short) boxes, but only ROT90CW is actually
# right-side up -- ROT90CCW is the upside-down candidate, which
# _bio_orientation_looks_correct must reject.
REAL_SFEIR_RAW_BIO_WORDS = [
    _w('CAN', 238, 53, 252, 88, 0.99),
    _w('28.08.2023', 620, 562, 640, 686, 0.99),
    _w('716833LBN6611019M33082791001086295', 793, 110, 834, 865, 0.99),
    _w('General', 609, 166, 628, 232, 0.99),
    _w('27.08.2033', 666, 563, 686, 689, 0.99),
    _w('name', 422, 584, 438, 630, 0.989),
    _w('NICOLAS', 472, 594, 491, 685, 0.989),
    _w('AJALTOUN', 571, 580, 592, 687, 0.989),
    _w('SFEIR', 314, 625, 331, 687, 0.988),
    _w('Libanaise', 180, 394, 211, 521, 0.988),
    _w('of', 546, 619, 566, 635, 0.987),
    _w('date', 645, 599, 668, 635, 0.987),
    _w('641312', 262, 25, 281, 112, 0.987),
    _w('of', 503, 392, 517, 409, 0.986),
    _w('LEBANESE', 522, 577, 542, 685, 0.986),
    _w('CHARBEL', 397, 585, 414, 685, 0.985),
    _w('NSFEIR', 740, 732, 773, 864, 0.984),
    _w('LR3371683', 257, 207, 277, 339, 0.982),
    _w('Sex', 505, 147, 520, 183, 0.981),
    _w('Date', 503, 414, 518, 452, 0.979),
    _w('République', 178, 531, 210, 682, 0.978),
    _w('Place', 544, 641, 566, 685, 0.978),
    _w('4', 805, 0, 835, 21, 0.975),
    _w('date', 602, 574, 620, 610, 0.975),
    _w('Name', 258, 639, 274, 686, 0.975),
    _w('01.11.1966', 528, 296, 547, 420, 0.975),
    _w('birth', 504, 352, 519, 388, 0.973),
    _w('Major', 608, 236, 627, 284, 0.963),
    _w('CHARBEL', 743, 531, 777, 685, 0.957),
    _w('/', 178, 683, 208, 703, 0.957),
    _w('<<', 743, 688, 774, 730, 0.951),
    _w('pe', 211, 651, 222, 669, 0.948),
    _w('/', 181, 371, 211, 386, 0.942),
    _w('Authority', 605, 371, 623, 445, 0.933),
    _w('Nationality', 499, 599, 517, 683, 0.924),
    _w('Code', 209, 522, 223, 556, 0.92),
    _w('Issuance', 600, 614, 619, 685, 0.915),
    _w('birthi', 546, 581, 568, 616, 0.915),
    _w('Lebanon', 177, 710, 209, 820, 0.9),
    _w('Expiry', 644, 637, 667, 683, 0.885),
    _w('Baissari', 611, 21, 630, 89, 0.869),
    _w('LBN', 227, 520, 244, 556, 0.867),
    _w('RL', 222, 392, 253, 439, 0.843),
    _w('/', 646, 585, 667, 596, 0.813),
    _w('/', 548, 566, 568, 576, 0.795),
    _w('/', 504, 333, 518, 346, 0.794),
    _w('<<<<', 804, 18, 835, 110, 0.787),
    _w('ather', 420, 632, 436, 671, 0.786),
    _w('Elias', 610, 120, 629, 161, 0.778),
    _w('/', 606, 358, 623, 368, 0.747),
    _w('EL', 611, 92, 628, 116, 0.727),
    _w('<<<<<<<<<<<<<<<<<<<<<<<<', 746, 0, 787, 531, 0.72),
    _w('of', 177, 827, 207, 850, 0.685),
    _w('/', 630, 405, 651, 416, 0.682),
    _w('Passport', 224, 309, 255, 381, 0.634),
    _w('O', 574, 547, 592, 562, 0.569),
    _w('.AL', 222, 275, 257, 439, 0.466),
    _w('c', 185, 858, 204, 869, 0.442),
    _w('GDGS', 629, 421, 652, 466, 0.389),
    _w('/', 499, 580, 516, 599, 0.308),
    _w('N', 227, 292, 255, 305, 0.218),
    _w(':', 177, 857, 207, 862, 0.198),
]

REAL_SFEIR_ROT90CW_BIO_WORDS = [
    _w('of', 237, 34, 262, 63, 0.992),
    _w('28.08.2023', 401, 477, 526, 498, 0.992),
    _w('SFEIR', 401, 170, 462, 188, 0.991),
    _w('CHARBEL', 402, 253, 500, 271, 0.988),
    _w('641312', 976, 118, 1062, 136, 0.988),
    _w('Passport', 132, 172, 217, 189, 0.988),
    _w('27.08.2033', 399, 523, 525, 544, 0.987),
    _w('Lebanon', 267, 34, 378, 65, 0.987),
    _w('NICOLAS', 403, 330, 492, 348, 0.986),
    _w('LR3371683', 749, 114, 877, 133, 0.986),
    _w('Place', 403, 401, 446, 420, 0.986),
    _w('/', 384, 36, 404, 65, 0.985),
    _w('République', 406, 35, 557, 66, 0.985),
    _w('of', 452, 403, 468, 420, 0.983),
    _w('LEBANESE', 402, 378, 509, 399, 0.98),
    _w('ublic', 166, 34, 228, 64, 0.98),
    _w('Passeport', 130, 153, 229, 170, 0.976),
    _w('Baissari', 998, 466, 1062, 486, 0.974),
    _w('birth', 698, 361, 735, 381, 0.972),
    _w('Passport', 705, 80, 780, 115, 0.97),
    _w('Date', 634, 360, 672, 380, 0.97),
    _w('name', 458, 274, 502, 297, 0.97),
    _w('date', 475, 458, 510, 479, 0.967),
    _w('CHARBEL', 404, 601, 553, 631, 0.966),
    _w('Libanaise', 565, 37, 693, 68, 0.96),
    _w('General', 855, 464, 921, 484, 0.957),
    _w('LBNSFEIR', 179, 599, 353, 629, 0.957),
    _w('birth', 472, 403, 502, 422, 0.955),
    _w('01.11.1966', 667, 386, 792, 405, 0.955),
    _w('of', 679, 360, 696, 379, 0.953),
    _w('Efias', 926, 465, 965, 485, 0.951),
    _w('Authority', 644, 461, 715, 481, 0.943),
    _w('N', 780, 84, 797, 115, 0.942),
    _w('/', 699, 38, 718, 67, 0.935),
    _w('date', 451, 502, 487, 524, 0.935),
    _w('Father', 401, 272, 453, 296, 0.925),
    _w('P', 133, 599, 153, 626, 0.919),
    _w('Nationality', 404, 357, 488, 374, 0.916),
    _w('AJALTOUN', 400, 428, 506, 452, 0.91),
    _w('name', 441, 191, 485, 211, 0.909),
    _w('/', 490, 357, 501, 374, 0.908),
    _w('Major', 803, 463, 851, 483, 0.902),
    _w('<', 157, 599, 177, 626, 0.88),
    _w('GDGS', 622, 488, 667, 508, 0.88),
    _w('Name', 400, 113, 447, 133, 0.877),
    _w('LBN', 532, 83, 565, 101, 0.86),
    _w('<<<<<<<<<<<<', 561, 603, 823, 634, 0.844),
    _w('/', 716, 462, 727, 480, 0.839),
    _w('RL', 647, 78, 692, 110, 0.828),
    _w('First', 401, 192, 435, 212, 0.828),
    _w('Tssuance', 399, 456, 470, 478, 0.806),
    _w('/', 794, 386, 798, 404, 0.77),
    _w('/', 489, 503, 501, 524, 0.768),
    _w('/', 506, 276, 517, 297, 0.768),
    _w('/', 450, 113, 462, 132, 0.759),
    _w('/', 511, 404, 521, 421, 0.721),
    _w('Expiry', 401, 500, 449, 523, 0.717),
    _w('/', 740, 361, 751, 380, 0.709),
    _w('El', 971, 466, 993, 484, 0.706),
    _w('<<', 359, 601, 400, 628, 0.697),
    _w('ope', 410, 68, 435, 80, 0.65),
    _w('/', 671, 488, 683, 508, 0.64),
]

REAL_SFEIR_ROT90CCW_BIO_WORDS = [
    _w('name', 776, 375, 820, 393, 0.992),
    _w('of', 1018, 610, 1043, 639, 0.992),
    _w('République', 723, 605, 873, 637, 0.99),
    _w('General', 358, 186, 423, 204, 0.989),
    _w('NICOLAS', 786, 323, 876, 342, 0.989),
    _w('name', 793, 458, 840, 475, 0.987),
    _w('date', 791, 146, 827, 169, 0.987),
    _w('SFEIR', 818, 482, 879, 501, 0.987),
    _w('LBNSFEIR', 923, 43, 1102, 71, 0.986),
    _w('Lebanon', 901, 608, 1013, 639, 0.986),
    _w('CHARBEL', 778, 399, 877, 419, 0.986),
    _w('Libanaise', 585, 605, 714, 635, 0.986),
    _w('641312', 217, 533, 303, 552, 0.986),
    _w('of', 811, 248, 827, 267, 0.986),
    _w('27.08.2033', 754, 127, 881, 147, 0.985),
    _w('Name', 830, 539, 878, 556, 0.985),
    _w('Place', 832, 248, 877, 269, 0.985),
    _w('LR3371683', 400, 536, 529, 557, 0.985),
    _w('28.08.2023', 754, 173, 877, 194, 0.984),
    _w('CHARBEL', 721, 42, 878, 69, 0.983),
    _w('date', 766, 194, 802, 211, 0.982),
    _w('LEBANESE', 770, 272, 877, 293, 0.982),
    _w('Passport', 1061, 482, 1148, 500, 0.98),
    _w('RL', 585, 562, 633, 592, 0.98),
    _w('birth', 775, 246, 807, 267, 0.979),
    _w('/', 876, 608, 894, 637, 0.977),
    _w('birth', 543, 291, 581, 312, 0.977),
    _w('01.11.1966', 488, 267, 612, 286, 0.973),
    _w('ublic', 1051, 609, 1114, 640, 0.971),
    _w('Date', 606, 293, 645, 314, 0.969),
    _w('Passeport', 1049, 501, 1147, 520, 0.962),
    _w('Passport', 501, 561, 571, 583, 0.962),
    _w('Father', 824, 376, 877, 394, 0.955),
    _w('Major', 427, 187, 476, 205, 0.949),
    _w('Nationality', 791, 298, 875, 315, 0.937),
    _w('Authority', 564, 190, 637, 208, 0.936),
    _w('/', 562, 605, 578, 634, 0.934),
    _w('P', 1126, 46, 1147, 72, 0.933),
    _w('Issuance', 806, 195, 877, 213, 0.91),
    _w('Baissan', 217, 184, 282, 202, 0.903),
    _w('of', 583, 292, 601, 312, 0.903),
    _w('<', 1104, 45, 1127, 71, 0.898),
    _w('Expiry', 830, 147, 876, 170, 0.875),
    _w('AJALTOUN', 773, 218, 881, 246, 0.875),
    _w('<<<', 663, 40, 722, 68, 0.864),
    _w('Elias', 311, 185, 354, 203, 0.812),
    _w('/', 777, 147, 788, 168, 0.811),
    _w('CAN', 250, 561, 279, 575, 0.804),
    _w('N', 484, 561, 496, 582, 0.8),
    _w('/', 757, 247, 766, 266, 0.797),
    _w('<<', 878, 43, 924, 70, 0.795),
    _w('/', 482, 267, 485, 284, 0.788),
    _w('N6611019M', 684, 0, 883, 17, 0.783),
    _w('LR33716832', 937, 0, 1152, 19, 0.766),
    _w('GDGS', 612, 163, 657, 187, 0.755),
    _w('/', 598, 164, 608, 186, 0.741),
    _w('/', 527, 291, 539, 310, 0.741),
    _w('EL', 285, 185, 308, 202, 0.736),
    _w('/', 551, 190, 561, 206, 0.666),
    _w('/', 452, 561, 465, 582, 0.65),
    _w('First', 842, 456, 879, 473, 0.519),
    _w('.', 468, 561, 473, 582, 0.426),
]


class MrzChecksumTest(unittest.TestCase):
    """Confirms the transcribed MRZ (Richard Bou Tayeh) is genuinely
    checksum-valid before it's trusted as a test fixture."""

    def test_real_lines_pass_every_checksum(self):
        mrz = parse_td3(_REAL_LINE1, _REAL_LINE2)
        self.assertTrue(mrz.passport_number_valid)
        self.assertTrue(mrz.dob_valid)
        self.assertTrue(mrz.expiry_valid)
        self.assertEqual(mrz.surname, "BOU TAYEH")
        self.assertEqual(mrz.given_names, "RICHARD")


class LooksRotated90Test(unittest.TestCase):
    """_looks_rotated_90 must flag both real sideways photos' original
    crops, and stay quiet once either has been rotated 90 degrees (either
    direction -- this check alone can't and isn't meant to tell the correct
    direction from the upside-down one, see _bio_orientation_looks_correct)."""

    def test_flags_richard_bou_tayehs_sideways_crop(self):
        self.assertTrue(_looks_rotated_90(REAL_ROTATED_BIO_WORDS))

    def test_flags_charbel_sfeirs_sideways_crop(self):
        self.assertTrue(_looks_rotated_90(REAL_SFEIR_RAW_BIO_WORDS))

    def test_does_not_flag_charbel_sfeirs_correctly_rotated_crop(self):
        self.assertFalse(_looks_rotated_90(REAL_SFEIR_ROT90CW_BIO_WORDS))

    def test_does_not_flag_charbel_sfeirs_upside_down_rotated_crop(self):
        # The whole point of _bio_orientation_looks_correct existing: this
        # check alone genuinely can't distinguish the wrong 90-degree
        # direction from the right one.
        self.assertFalse(_looks_rotated_90(REAL_SFEIR_ROT90CCW_BIO_WORDS))

    def test_does_not_flag_too_few_words_to_judge(self):
        self.assertFalse(_looks_rotated_90(REAL_ROTATED_BIO_WORDS[:2]))


class BioOrientationLooksCorrectTest(unittest.TestCase):
    """_bio_orientation_looks_correct is what actually disambiguates the two
    90-degree candidates on Charbel Sfeir's real photo -- confirmed here
    against both real rotated word sets directly."""

    def test_accepts_the_correctly_rotated_crop(self):
        self.assertTrue(_bio_orientation_looks_correct(REAL_SFEIR_ROT90CW_BIO_WORDS))

    def test_rejects_the_upside_down_crop(self):
        self.assertFalse(_bio_orientation_looks_correct(REAL_SFEIR_ROT90CCW_BIO_WORDS))

    def test_accepts_when_fewer_than_two_anchors_are_found(self):
        # Not enough evidence to reject -- other fallbacks are better
        # placed to handle a sparsely-labeled photo than a coin-flip here.
        sparse = [w for w in REAL_SFEIR_ROT90CW_BIO_WORDS if w.text not in ("Father", "Nationality", "Place")]
        self.assertTrue(_bio_orientation_looks_correct(sparse))


class ResolveBioWordsTest(unittest.TestCase):
    """_resolve_bio_words end to end on Charbel Sfeir's real three-orientation
    data: starting from the real sideways crop, it must land on the
    rot90cw candidate (the real correct one), not the rot90ccw one (real,
    but upside down), and extract the real father's-name/place-of-birth
    values from it."""

    def setUp(self):
        self.image = _make_image(_REAL_PHOTO_HEIGHT, _REAL_PHOTO_WIDTH)
        self.calls = []

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        self.calls.append(image.shape)
        call_number = len(self.calls)
        if call_number == 1:
            return OcrResult(full_text="", words=REAL_SFEIR_RAW_BIO_WORDS)
        if call_number == 2:
            # _BIO_ROTATION_ATTEMPTS tries clockwise first -- the real
            # correct direction for this photo.
            return OcrResult(full_text="", words=REAL_SFEIR_ROT90CW_BIO_WORDS)
        return OcrResult(full_text="", words=REAL_SFEIR_ROT90CCW_BIO_WORDS)

    def test_adopts_the_correct_rotation_without_trying_the_second_one(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            oriented_image, words = _resolve_bio_words(self.image, None, [])

        self.assertIsNot(oriented_image, self.image)
        self.assertEqual(len(self.calls), 2)  # original + rot90cw only
        texts = {w.text for w in words}
        self.assertIn("NICOLAS", texts)
        self.assertIn("AJALTOUN", texts)

    def test_falls_back_to_the_original_crop_when_no_rotation_looks_right(self):
        def fake_ocr(image, language_hints=None, **kwargs):
            self.calls.append(image.shape)
            if len(self.calls) == 1:
                return OcrResult(full_text="", words=REAL_SFEIR_RAW_BIO_WORDS)
            # Both 90-degree candidates come back upside down -- neither
            # should be adopted.
            return OcrResult(full_text="", words=REAL_SFEIR_ROT90CCW_BIO_WORDS)

        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=fake_ocr):
            oriented_image, words = _resolve_bio_words(self.image, None, [])

        self.assertIs(oriented_image, self.image)
        self.assertTrue(words)  # still falls back to a usable (if wrong) read


class TryLocateMrzWithRotationTest(unittest.TestCase):
    """Unit tests for _try_locate_mrz_with_rotation in isolation -- kept as
    regression coverage for the MRZ-side rotation probe, which neither real
    rotated photo actually ended up needing (see module docstring) but which
    is still valid defense in depth for a future photo whose MRZ can't be
    read sideways."""

    def setUp(self):
        self.image = _make_image(_REAL_PHOTO_HEIGHT, _REAL_PHOTO_WIDTH)
        self.band = _crop_mrz_band(self.image)

    def test_succeeds_at_band_without_trying_any_rotation(self):
        calls = []

        def fake_ocr(image, language_hints=None, **kwargs):
            calls.append(image.shape)
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])

        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=fake_ocr):
            result = _try_locate_mrz_with_rotation(self.image, self.band, None, [])

        self.assertIsNotNone(result)
        oriented_image, lines, ocr_result = result
        self.assertIs(oriented_image, self.image)
        self.assertEqual(len(calls), 1)

    def test_falls_back_to_a_rotation_when_both_zero_degree_tiers_fail(self):
        call_count = 0

        def fake_ocr(image, language_hints=None, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return OcrResult(full_text="RANDOM UNRELATED TEXT", words=[])
            return OcrResult(full_text=_REAL_MRZ_TEXT, words=[OcrWord("X", 0.9, (0, 0, 10, 10))])

        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=fake_ocr):
            result = _try_locate_mrz_with_rotation(self.image, self.band, None, [])

        self.assertIsNotNone(result)
        oriented_image, lines, ocr_result = result
        self.assertEqual(call_count, 3)
        self.assertEqual(oriented_image.shape, (_REAL_PHOTO_WIDTH, _REAL_PHOTO_HEIGHT, 3))
        self.assertIsNot(oriented_image, self.image)

    def test_returns_none_when_no_orientation_has_an_mrz(self):
        def fake_ocr(image, language_hints=None, **kwargs):
            return OcrResult(full_text="RANDOM UNRELATED TEXT", words=[])

        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=fake_ocr):
            result = _try_locate_mrz_with_rotation(self.image, self.band, None, [])

        self.assertIsNone(result)


class EndToEndRotationTest(unittest.TestCase):
    """Exercises extract_passport_data itself, end to end, on Charbel
    Sfeir's real photo dimensions and real three-orientation bio data --
    the MRZ tiers all fail (matching what actually happened -- this photo's
    MRZ wasn't reachable in the mocked data here), but bio-page extraction
    must still land on the correct rotation and the correct field values."""

    def setUp(self):
        self.tmp_dir = Path(tempfile.mkdtemp())
        original = _make_image(_REAL_PHOTO_HEIGHT, _REAL_PHOTO_WIDTH)
        self.image_path = str(self.tmp_dir / "passport.png")
        cv2.imwrite(self.image_path, original)

        self.raw_bio_shape = crop_region(original, BIO_SEARCH_REGION).shape
        rotated = cv2.rotate(original, cv2.ROTATE_90_CLOCKWISE)
        # A 90-degree rotation of a rectangular image swaps height and
        # width regardless of direction, so the clockwise and
        # counter-clockwise candidates are the same SHAPE -- can't tell
        # them apart by shape alone. _BIO_ROTATION_ATTEMPTS tries clockwise
        # first, so the first call at this shape is that candidate and the
        # second (if reached) is counter-clockwise -- tracked by call order
        # below instead.
        self.rotated_bio_shape = crop_region(rotated, BIO_SEARCH_REGION).shape
        self.assertNotEqual(self.raw_bio_shape, self.rotated_bio_shape)
        self.rotated_bio_calls = 0

    def _fake_ocr(self, image, language_hints=None, **kwargs):
        shape = image.shape
        if shape == self.raw_bio_shape:
            return OcrResult(full_text="", words=REAL_SFEIR_RAW_BIO_WORDS)
        if shape == self.rotated_bio_shape:
            self.rotated_bio_calls += 1
            if self.rotated_bio_calls == 1:
                return OcrResult(full_text="", words=REAL_SFEIR_ROT90CW_BIO_WORDS)
            return OcrResult(full_text="", words=REAL_SFEIR_ROT90CCW_BIO_WORDS)
        # Every MRZ-tier call (band, whole photo, and every whole-photo
        # rotation probe) -- none of them matter for this test, which is
        # about bio-page extraction only.
        return OcrResult(full_text="RANDOM UNRELATED TEXT", words=[])

    def test_bio_fields_resolve_correctly_from_the_real_photo_data(self):
        with mock.patch("ocr.passport_ocr.ocr_image_array", side_effect=self._fake_ocr):
            result = extract_passport_data(self.image_path)

        self.assertEqual(result.father_name.value, "NICOLAS")
        self.assertEqual(result.place_of_birth.value, "AJALTOUN")


if __name__ == "__main__":
    unittest.main()
