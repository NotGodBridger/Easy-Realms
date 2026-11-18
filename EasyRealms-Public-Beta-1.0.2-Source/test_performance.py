import unittest

from performance import ProcessMonitor, format_memory, format_uptime, load_message


class PerformanceTests(unittest.TestCase):
    def test_human_readable_values(self):
        self.assertEqual(format_memory(512 * 1024**2), "512 MB")
        self.assertEqual(format_memory(3 * 1024**3), "3.0 GB")
        self.assertEqual(format_uptime(45), "45s")
        self.assertEqual(format_uptime(3725), "1h 02m")

    def test_deterministic_cpu_sample(self):
        readings = iter([(10.0, 100), (12.0, 200)])
        times = iter([100.0, 100.0, 102.0])
        monitor = ProcessMonitor(
            reader=lambda process_id: next(readings),
            clock=lambda: next(times),
            cpu_count=4,
        )
        monitor.reset(123)
        sample = monitor.sample()
        self.assertAlmostEqual(sample.cpu_percent, 25.0)
        self.assertEqual(sample.memory_bytes, 200)
        self.assertEqual(sample.uptime_seconds, 2.0)

    def test_load_messages_prioritise_serious_pressure(self):
        self.assertIn("very high", load_message(95, 100, 4))
        self.assertIn("configured limit", load_message(10, int(3.8 * 1024**3), 4))
        self.assertIn("healthy", load_message(20, 512 * 1024**2, 4))


if __name__ == "__main__":
    unittest.main()
