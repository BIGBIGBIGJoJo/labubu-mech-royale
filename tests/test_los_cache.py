"""Guard exact within-ray reuse without losing obstruction samples."""
import unittest
from arena_map import ArenaMap


class TerrainEndpointReuseTests(unittest.TestCase):
    def arena(self, cuts, ground):
        arena = ArenaMap.__new__(ArenaMap)
        arena.available = True
        arena._candidates = lambda *args: ()
        arena._terrain_cuts = lambda *args: cuts
        calls = []
        def height(x, y):
            calls.append((x, y))
            return ground(x, y)
        arena.ground_height = height
        return arena, calls

    def test_shared_endpoints_are_evaluated_once(self):
        arena, calls = self.arena([0, .25, .5, .75, 1], lambda x, y: 0)
        self.assertTrue(arena.line_of_fire((0, 0, 1), (1, 0, 1)))
        self.assertEqual(len(calls), 9)
        for x in (.25, .5, .75):
            self.assertEqual(calls.count((x, 0)), 1)

    def test_skipped_positive_gap_recomputes_the_unmatched_endpoint(self):
        after_gap = .40000000005
        arena, calls = self.arena([0, .4, after_gap, 1],
                                  lambda x, y: 1 if x == after_gap else 0)
        self.assertFalse(arena.line_of_fire((0, 0, 1), (1, 0, 1)))
        self.assertIn((after_gap, 0), calls)

    def test_duplicate_cut_keeps_valid_endpoint_reuse(self):
        arena, calls = self.arena([0, .4, .4, 1], lambda x, y: 0)
        self.assertTrue(arena.line_of_fire((0, 0, 1), (1, 0, 1)))
        self.assertEqual(calls.count((.4, 0)), 1)
        self.assertEqual(len(calls), 5)

    def test_interior_quadratic_obstruction_is_still_detected(self):
        arena, _ = self.arena([0, 1], lambda x, y: .98 - 4 * (x - .3) ** 2)
        self.assertFalse(arena.line_of_fire((0, 0, 1), (1, 0, 1)))

    def test_no_clearance_is_reused_across_queries(self):
        level = [0]
        arena, _ = self.arena([0, .5, 1], lambda x, y: level[0])
        self.assertTrue(arena.line_of_fire((0, 0, 1), (1, 0, 1)))
        level[0] = 1
        self.assertFalse(arena.line_of_fire((0, 0, 1), (1, 0, 1)))


if __name__ == '__main__':
    unittest.main()
