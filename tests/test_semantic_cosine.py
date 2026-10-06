import math
import random

import pytest

from companion_memoryos.semantic_index import cosine


@pytest.mark.parametrize("dimensions", [2, 256, 512])
def test_fast_cosine_matches_scalar_reference(dimensions):
    rng = random.Random(20260929)
    for _ in range(30):
        left = [rng.uniform(-2, 2) for _ in range(dimensions)]
        right = [rng.uniform(-2, 2) for _ in range(dimensions)]
        norm = math.sqrt(sum(x * x for x in left))
        expected = sum(a * b for a, b in zip(left, right, strict=True)) / (
            norm * math.sqrt(sum(x * x for x in right))
        )
        assert cosine(left, right) == pytest.approx(expected, abs=1e-12)
        assert cosine(left, right, left_norm=norm) == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    "left,right", [([], []), ([1], [1, 2]), ([0, 0], [1, 2]), ([1, 2], [0, 0])]
)
def test_fast_cosine_empty_mismatched_and_zero_vectors(left, right):
    assert cosine(left, right) == 0
