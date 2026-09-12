"""周次展开必须先检查资源上限，不能先分配后校验。"""
from unittest.mock import patch

import pytest

from server.services.ustc_schedule import UstcScheduleParseError, _parse_week_values


def test_huge_week_range_is_rejected_before_expansion() -> None:
    with patch("server.services.ustc_schedule.range", side_effect=AssertionError("range allocated"), create=True):
        with pytest.raises(UstcScheduleParseError, match="范围过大"):
            _parse_week_values("1-999999999周")


def test_repeated_week_ranges_have_a_total_budget() -> None:
    with pytest.raises(UstcScheduleParseError, match="范围过大"):
        _parse_week_values(",".join(["1-500"] * 3) + "周")


def test_normal_discontinuous_and_alternate_weeks_are_preserved() -> None:
    assert _parse_week_values("1-5(单),8,10-12(双)周") == [1, 3, 5, 8, 10, 12]
