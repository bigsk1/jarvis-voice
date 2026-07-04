#!/usr/bin/env python3
"""
Regression tests for shared TTS normalization.

Run:
    python3 tests/test_tts_normalizer.py
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT / "lib"))

from security_utils import sanitize_for_speech
from tts_normalizer import (
    normalize_tts_text,
    strip_llm_citation_artifacts,
    strip_speech_tags_for_display,
    validate_tts_profile,
)


class TtsNormalizerTests(unittest.TestCase):
    def test_strip_llm_citation_artifacts_removes_pua_and_turn_refs(self):
        self.assertEqual(strip_llm_citation_artifacts("A\ue200\ue202B"), "AB")
        cite_turn = "See Foo cite turn0search0 bar."
        ct = strip_llm_citation_artifacts(cite_turn)
        self.assertNotIn("turn0search0", ct.lower())
        self.assertNotIn("cite", ct.lower())
        standalone = "x turn0news0 y"
        self.assertEqual(strip_llm_citation_artifacts(standalone).strip(), "x y")

    def test_strip_speech_tags_for_display_applies_citation_cleanup(self):
        messy = "Hello.\ue200cite\ue201turn0search0\ue202 Done."
        cleaned = strip_speech_tags_for_display(messy)
        self.assertNotIn("\ue200", cleaned)
        self.assertNotIn("turn0search0", cleaned.lower())

    def test_default_normalizer_removes_links_and_visual_noise(self):
        normalized = normalize_tts_text(
            "Weather update. Sources: https://example.com/report\n"
            "Read [forecast details](https://weather.example.com/day).\n"
            "Saved at stash://space/file and www.example.org/path"
        )

        self.assertIn("forecast details", normalized)
        self.assertIn("saved to stash", normalized)
        self.assertNotIn("https://", normalized)
        self.assertNotIn("www.example.org", normalized)
        self.assertNotIn("Sources:", normalized)

    def test_default_normalizer_removes_bare_stash_space_id(self):
        normalized = normalize_tts_text(
            "The full articles are saved in stash space_20260704_232042_7d345c6a."
        )

        self.assertEqual(normalized, "The full articles are saved in stash.")
        self.assertNotIn("space_", normalized)

    def test_default_normalizer_removes_inline_legacy_dashed_stash_space_id(self):
        normalized = normalize_tts_text(
            "Saved in stash space_2026-07-04_232042_7d345c6a, ready to review."
        )

        self.assertEqual(normalized, "Saved in stash, ready to review.")

    def test_default_normalizer_removes_parenthesized_bare_url_examples(self):
        normalized = normalize_tts_text(
            "Preview limited; full details like exact hours in Yelp results "
            "(e.g., yelp.com/search?find_desc=golf+driving+ranges&find_loc=Portland). "
            "Need more specifics?"
        )

        self.assertEqual(
            normalized,
            "Preview limited; full details like exact hours in Yelp results. Need more specifics?"
        )
        self.assertNotIn("yelp.com", normalized)
        self.assertNotIn("for example", normalized)

    def test_default_normalizer_strips_emoji_for_tts(self):
        normalized = normalize_tts_text(
            "Done. Great work \U0001F389 and thanks \U0001F64F. Robot \U0001F916 skull \U0001F480 flag \U0001F1FA\U0001F1F8."
        )
        self.assertNotIn("\U0001F389", normalized)
        self.assertNotIn("\U0001F916", normalized)
        self.assertNotIn("\U0001F480", normalized)
        self.assertIn("Done.", normalized)
        self.assertIn("Great work", normalized)
        self.assertIn("thanks", normalized)
        self.assertIn("Robot", normalized)
        self.assertIn("skull", normalized)

    def test_default_normalizer_converts_units_for_speech(self):
        normalized = normalize_tts_text(
            "Tonight is 34°F with a backup low of 10°C and 25% rain."
        )

        self.assertIn("34 degrees", normalized)
        self.assertIn("10 degrees Celsius", normalized)
        self.assertIn("25 percent", normalized)
        self.assertNotIn("°F", normalized)
        self.assertNotIn("°C", normalized)

    def test_default_normalizer_expands_common_english_abbreviations(self):
        normalized = normalize_tts_text(
            "Meet at 9:30 a.m. on Apr. 4. Bring No. 5 and Nos. 7 to 9, e.g. the red samples, etc."
        )

        self.assertIn("9:30 AM", normalized)
        self.assertIn("April 4", normalized)
        self.assertIn("number 5", normalized)
        self.assertIn("numbers 7 to 9", normalized)
        self.assertIn("for example", normalized)
        self.assertIn("et cetera", normalized)

    def test_default_normalizer_expands_ie_phrase(self):
        normalized = normalize_tts_text(
            "This is a verification task, i.e. compare the saved value with the live result."
        )

        self.assertIn("that is", normalized)
        self.assertNotIn("i.e.", normalized)

    def test_default_normalizer_avoids_duplicate_version_prefix(self):
        normalized = normalize_tts_text(
            "The file was version v2.4.10-beta and the prior build was version v1.9."
        )

        self.assertIn("version 2.4.10-beta", normalized)
        self.assertIn("version 1.9", normalized)
        self.assertNotIn("version version", normalized)

    def test_default_normalizer_handles_logistics_and_fraction_phrases(self):
        normalized = normalize_tts_text(
            "Order #A-17XQ-2049 arrives Tue., Apr. 9 at 8:05 a.m. unless temp. drops below 32°F "
            "or wind hits 20–25 mph. Call 555-0199 ext. 42 before 11:59 p.m. "
            "Backup quote was €999.95 plus 7.25% tax, and 1/2, 1/4, and 3/8 passed."
        )

        self.assertIn("#A-17XQ-2049", normalized)
        self.assertIn("Tuesday, April 9", normalized)
        self.assertIn("8:05 AM", normalized)
        self.assertIn("temperature drops below 32 degrees", normalized)
        self.assertIn("20 to 25 miles per hour", normalized)
        self.assertIn("extension 42", normalized)
        self.assertIn("11:59 PM", normalized)
        self.assertIn("999 euros and 95 cents", normalized)
        self.assertIn("7.25 percent", normalized)
        self.assertIn("one half", normalized)
        self.assertIn("one quarter", normalized)
        self.assertIn("three eighths", normalized)

    def test_default_normalizer_handles_threshold_symbols_duration_and_more_fractions(self):
        normalized = normalize_tts_text(
            "Arrives Wed., Apr. 10th if temp > 40°F and wind < 15–18 mph. "
            "Retry in 00:45. If 1/3, 2/5, and 7/12 tests pass, we're good."
        )

        self.assertIn("Wednesday, April 10th", normalized)
        self.assertIn("temperature greater than 40 degrees", normalized)
        self.assertIn("wind less than 15 to 18 miles per hour", normalized)
        self.assertIn("Retry in 45 seconds", normalized)
        self.assertIn("one third", normalized)
        self.assertIn("two fifths", normalized)
        self.assertIn("seven twelfths", normalized)

    def test_default_normalizer_handles_compact_thresholds_with_percent_and_fractional_ram(self):
        normalized = normalize_tts_text(
            "CPU usage hit 87.5% @ 14:23:45 UTC—reboot srv-10.0.1.25 if >90% by 15:30 or RAM <2/5 GB."
        )

        self.assertIn("87.5 percent", normalized)
        self.assertIn("greater than 90 percent", normalized)
        self.assertIn("RAM less than two fifths gigabytes", normalized)

    def test_weather_profile_strips_iso_dates(self):
        normalized = normalize_tts_text(
            "Fri 2026-04-04 high 61°F. Sat 2026-04-05 low 40°F.",
            profile="weather_watch",
        )

        self.assertIn("Fri high 61 degrees", normalized)
        self.assertIn("Sat low 40 degrees", normalized)
        self.assertNotIn("2026-04-04", normalized)
        self.assertNotIn("2026-04-05", normalized)

    def test_price_quote_profile_normalizes_market_language(self):
        normalized = normalize_tts_text(
            "Bitcoin is currently $67,000, +1.27% in the last 24h. Solana is $80.54. Pepe is $0.0042.",
            profile="price_quote",
        )

        self.assertIn("67,000 dollars", normalized)
        self.assertIn("up 1.27 percent", normalized)
        self.assertIn("24 hours", normalized)
        self.assertIn("80 dollars and 54 cents", normalized)
        self.assertIn("0.0042 dollars", normalized)

    def test_timestamped_profile_converts_iso_dates_and_datetimes(self):
        normalized = normalize_tts_text(
            "Created at 2026-04-04T09:30:00Z. Follow-up at 2026-04-04 17:45:00.",
            profile="timestamped",
        )

        self.assertIn("April 4, 2026 at 9:30 AM UTC", normalized)
        self.assertIn("April 4, 2026 at 5:45 PM", normalized)
        self.assertNotIn("2026-04-04T09:30:00Z", normalized)
        self.assertNotIn("2026-04-04 17:45:00", normalized)

    def test_camera_alert_profile_smooths_camera_phrasing(self):
        normalized = normalize_tts_text(
            "🚨 Person: Front Door. Package: Garage Camera. Camera Offline: Driveway. SMOKE/CO ALARM: Hallway.",
            profile="camera_alert",
        )

        self.assertIn("Alert Person at Front Door", normalized)
        self.assertIn("Package at Garage Camera", normalized)
        self.assertIn("Camera offline at Driveway", normalized)
        self.assertIn("smoke or carbon monoxide alarm: Hallway", normalized)

    def test_legacy_sanitize_wrapper_matches_default_normalizer(self):
        sample = "Sources: https://example.com 34°F [report](https://example.com)"
        self.assertEqual(sanitize_for_speech(sample), normalize_tts_text(sample))

    def test_default_normalizer_strips_speech_tag_markup(self):
        normalized = normalize_tts_text(
            'Testing <excited>xAI tags</excited>. [pause] '
            '<whisper>It is a secret.</whisper> <slow>right here</slow>.'
        )

        self.assertEqual(
            normalized,
            "Testing xAI tags. It is a secret. right here."
        )
        self.assertNotIn("less than", normalized)
        self.assertNotIn("[pause]", normalized)
        self.assertNotIn("<whisper>", normalized)

    def test_xai_normalizer_preserves_supported_speech_tags(self):
        normalized = normalize_tts_text(
            'Testing <excited>xAI tags</excited>. [pause] '
            '"Really? [laugh] That is incredible!" '
            '<whisper>It is a secret.</whisper> '
            '<slow><soft>Goodnight, sleep well.</soft></slow>',
            preserve_xai_tags=True,
        )

        self.assertIn("Testing xAI tags.", normalized)
        self.assertIn("[pause]", normalized)
        self.assertIn("[laugh]", normalized)
        self.assertIn("<whisper>It is a secret.</whisper>", normalized)
        self.assertIn("<slow><soft>Goodnight, sleep well.</soft></slow>", normalized)
        self.assertNotIn("<excited>", normalized)
        self.assertNotIn("less than", normalized)

    def test_display_stripper_removes_tts_tags_without_recondensing_text(self):
        display = strip_speech_tags_for_display(
            "<soft>Okay, let's begin.</soft> [pause]\n\n"
            "- <whisper>Secret item</whisper>\n"
            "- <slow><emphasis>Important item</emphasis></slow>"
        )

        self.assertEqual(
            display,
            "Okay, let's begin.\n\n- Secret item\n- Important item"
        )
        self.assertNotIn("[pause]", display)
        self.assertNotIn("<soft>", display)
        self.assertNotIn("<whisper>", display)

    def test_malformed_wrapping_speech_tag_is_repaired_for_xai_and_stripped_for_display(self):
        sample = "That's hilarious [laugh] [slow>did you see that?</slow>"

        speech = normalize_tts_text(sample, preserve_xai_tags=True)
        display = strip_speech_tags_for_display(speech)

        self.assertEqual(speech, "That's hilarious [laugh] <slow>did you see that?</slow>")
        self.assertEqual(display, "That's hilarious did you see that?")
        self.assertNotIn("[slow>", display)

    def test_validate_tts_profile_allows_known_profiles(self):
        self.assertEqual(validate_tts_profile("weather_watch"), "weather_watch")
        self.assertEqual(validate_tts_profile("camera_alert"), "camera_alert")
        self.assertEqual(validate_tts_profile("price_quote"), "price_quote")
        self.assertEqual(validate_tts_profile("timestamped"), "timestamped")

    def test_validate_tts_profile_treats_missing_or_blank_as_none(self):
        self.assertIsNone(validate_tts_profile(None))
        self.assertIsNone(validate_tts_profile(""))
        self.assertIsNone(validate_tts_profile("   "))

    def test_validate_tts_profile_rejects_unknown_profile(self):
        with self.assertRaises(ValueError) as ctx:
            validate_tts_profile("weather_magic")

        self.assertIn("Unsupported TTS profile", str(ctx.exception))
        self.assertIn("weather_watch", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
