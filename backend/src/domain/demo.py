"""两期榆桥培训中心的虚拟受理记录和确认回执。"""

from .spec import CHANNELS, PROGRAMS


# 顺序与公开名册一致，每格为去重受理数、确认报名数。
_NOVEMBER = (
    ((20, 12), (11, 5), (5, 4)),
    ((18, 8), (14, 5), (13, 7)),
    ((12, 6), (15, 9), (10, 5)),
)
_OCTOBER = (((20, 12), (11, 5), (12, 5)), *_NOVEMBER[1:])

_ADDITIONS = (
    ("YQ-ADD-01", "2026-11-08", "社区转介", "养老照护", True),
    ("YQ-ADD-02", "2026-11-09", "公众号", "电工基础", False),
    ("YQ-ADD-03", "2026-11-10", "就业服务站", "烘焙实训", True),
    ("YQ-ADD-04", "2026-11-11", "社区转介", "电工基础", False),
    ("YQ-ADD-05", "2026-11-12", "公众号", "烘焙实训", True),
)
# 修订批次中 11 月的归属迁移、退出、撤销确认与补登确认。
_MOVES = {
    "YQ-11-003": ("公众号", "电工基础"),
    "YQ-21-004": ("就业服务站", "烘焙实训"),
    "YQ-32-006": ("社区转介", "养老照护"),
}
_EXITS = {"YQ-12-011", "YQ-33-010"}
_WITHDRAWN = {"YQ-11-005", "YQ-31-004"}
_ADDED_CONFIRMATIONS = {"YQ-12-006"}


def demo_rows() -> list[dict]:
    rows = []
    for period, grid in (("2026-10", _OCTOBER), ("2026-11", _NOVEMBER)):
        for channel_index, channel in enumerate(CHANNELS):
            for program_index, program in enumerate(PROGRAMS):
                total, confirmed = grid[channel_index][program_index]
                for index in range(total):
                    intake = {
                        "learner_id": f"YQ-{channel_index + 1}{program_index + 1}-{index + 1:03d}",
                        "intake_date": f"{period}-06",
                        "channel": channel,
                        "program": program,
                        "enrolled": False,
                    }
                    rows.append(intake)
                    if index < confirmed:
                        rows.append({**intake, "intake_date": f"{period}-18", "enrolled": True})
                    if index == 0:
                        rows.append(dict(intake))
                        rows.append({**intake, "intake_date": f"{period}-20",
                                     "channel": CHANNELS[(channel_index + 1) % len(CHANNELS)]})
    return rows


def revised_rows() -> list[dict]:
    """A re-checked November: three learners moved channel and program, two left the
    roster, two confirmations were withdrawn, one was added and five learners were new."""
    revised = []
    for row in demo_rows():
        learner = row["learner_id"]
        if row["intake_date"].startswith("2026-11"):
            if learner in _EXITS:
                continue
            if learner in _MOVES:
                channel, program = _MOVES[learner]
                row = {**row, "channel": channel, "program": program}
            if learner in _WITHDRAWN:
                row = {**row, "enrolled": False}
            if learner in _ADDED_CONFIRMATIONS:
                row = {**row, "enrolled": True}
        revised.append(row)
    revised.extend({"learner_id": learner, "intake_date": day, "channel": channel,
                    "program": program, "enrolled": enrolled}
                   for learner, day, channel, program, enrolled in _ADDITIONS)
    return revised

