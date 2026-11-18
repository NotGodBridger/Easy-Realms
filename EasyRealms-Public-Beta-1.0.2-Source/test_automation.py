import unittest

from automation import parse_player_count, recommend_resources, restart_decision, total_memory_gb


class AutomationTests(unittest.TestCase):
    def test_memory_detection_is_positive(self):
        self.assertGreater(total_memory_gb(), 0)

    def test_low_memory_keeps_safe_reserve(self):
        result = recommend_resources(4, "Vanilla", True)
        self.assertEqual(result["ram_gb"], 1)
        self.assertLessEqual(result["view_distance"], 5)
        self.assertTrue(result["warning"])

    def test_fabric_and_paper_profiles_differ(self):
        fabric = recommend_resources(16, "Fabric", True)
        paper = recommend_resources(16, "Paper", True)
        self.assertGreaterEqual(fabric["ram_gb"], paper["ram_gb"])
        self.assertLess(fabric["view_distance"], paper["view_distance"])

    def test_bedrock_does_not_allocate_java_memory(self):
        result = recommend_resources(16, "Bedrock", True)
        self.assertEqual(result["ram_gb"], 0)
        self.assertGreaterEqual(result["view_distance"], 8)

    def test_parses_java_player_count(self):
        self.assertEqual(parse_player_count("There are 2 of a max of 20 players online: Alex, Sam"), 2)

    def test_parses_bedrock_player_count(self):
        self.assertEqual(parse_player_count("There are 0/10 players online:"), 0)

    def test_crash_restart_limit_and_window(self):
        allowed, times = restart_decision([1, 2, 3], 4, limit=3, window_seconds=10)
        self.assertFalse(allowed); self.assertEqual(times, [1.0, 2.0, 3.0])
        allowed, times = restart_decision([1, 2, 3], 20, limit=3, window_seconds=10)
        self.assertTrue(allowed); self.assertEqual(times, [20.0])


if __name__ == "__main__":
    unittest.main()
