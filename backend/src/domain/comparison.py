"""同月两批受理记录的学员对齐与三类变化归因。

沿用月报的学员月度去重：每名学员每月只保留最早受理日的渠道与项目归属，
同月存在归属项目的确认报名即记为一次转化。两批记录按学员编号对齐后，
把转化率之差分解为「学员增减」「归属变动」「确认变化」三类变化的影响。

新建与退出按各自批次的归属和确认计；共同学员的渠道、项目与确认状态
分别由归属变动和确认变化两类操作调整。三类变化按全部六种顺序试算，
取每项边际影响的平均值（Shapley 值），空组合按零计。因此三项归因之和
恒等于新批次转化率减旧批次转化率。
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from itertools import permutations

from .analysis import monthly_learners
from .spec import CHANNELS, PROGRAMS

CHURN, ASSIGNMENT, CONFIRMATION = 1, 2, 4
_PLAYERS = (CHURN, ASSIGNMENT, CONFIRMATION)
_ONE_DP = Decimal("0.1")
FULL = CHURN | ASSIGNMENT | CONFIRMATION


def validate_period(period):
    try:
        if not isinstance(period, str) or date.fromisoformat(f"{period}-01").isoformat()[:7] != period:
            raise ValueError
    except ValueError:
        raise ValueError("统计月份须为有效的 YYYY-MM。") from None
    return period


def _quantize(value):
    return Decimal(str(value)).quantize(_ONE_DP, rounding=ROUND_HALF_UP)


def _signed(value):
    value = _quantize(value)
    if value == 0:
        return "0.0"
    return f"{value:+.1f}"


def _rate(state, matches):
    confirmed = total = 0
    for channel, program, enrolled in state.values():
        if matches(channel, program):
            total += 1
            confirmed += int(enrolled)
    # 空组合按零计，避免零去重受理时出现未定义比率。
    return (confirmed / total if total else 0.0), total, confirmed


def _groups():
    groups = [("总体", "总体", "总体", "总体", lambda channel, program: True)]
    groups += [("渠道", channel, channel, "", (lambda value: lambda channel, program: channel == value)(channel))
               for channel in CHANNELS]
    groups += [("项目", program, "", program, (lambda value: lambda channel, program: program == value)(program))
               for program in PROGRAMS]
    groups += [("组合", f"{channel} × {program}", channel, program,
                (lambda left, right: lambda channel, program: channel == left and program == right)(channel, program))
               for channel in CHANNELS for program in PROGRAMS]
    return groups


def _column(key, label):
    return {"key": key, "label": label}


def _table(title, columns, rows):
    return {"title": title, "columns": columns, "rows": rows}


def compare(old_rows, new_rows, period, old_name, new_name):
    """Return the learner-aligned attribution of the two batches' rates."""
    validate_period(period)
    old = monthly_learners(old_rows, period)
    new = monthly_learners(new_rows, period)
    if not old and not new:
        raise ValueError(f"两个批次在 {period} 都没有去重受理记录，无法对比。")

    common = old.keys() & new.keys()
    entries = new.keys() - old.keys()
    states = {}

    def state_for(mask):
        if mask in states:
            return states[mask]
        if mask & CHURN:
            state = {learner: old[learner] for learner in common}
            state.update({learner: new[learner] for learner in entries})
        else:
            state = dict(old)
        if mask & ASSIGNMENT:
            for learner in common:
                if learner in state:
                    previous = state[learner]
                    state[learner] = (new[learner][0], new[learner][1], previous[2])
        if mask & CONFIRMATION:
            for learner in common:
                if learner in state:
                    previous = state[learner]
                    state[learner] = (previous[0], previous[1], new[learner][2])
        states[mask] = state
        return state

    groups = _groups()
    measured = {}

    def measure(mask, index):
        key = (mask, index)
        if key not in measured:
            measured[key] = _rate(state_for(mask), groups[index][4])
        return measured[key]

    def value(mask, index, base):
        if mask == 0:
            return 0.0
        return measure(mask, index)[0] - base

    def shapley(index, base):
        totals = {player: 0.0 for player in _PLAYERS}
        for order in permutations(_PLAYERS):
            mask = 0
            previous = 0.0
            for player in order:
                mask |= player
                current = value(mask, index, base)
                totals[player] += current - previous
                previous = current
        return {player: totals[player] / 6 for player in _PLAYERS}

    rows = []
    for index, (scope, label, channel, program, _) in enumerate(groups):
        old_rate, old_total, old_confirmed = measure(0, index)
        new_rate, new_total, new_confirmed = measure(FULL, index)
        old_percent = _quantize(old_rate * 100)
        new_percent = _quantize(new_rate * 100)
        delta = new_percent - old_percent
        effects = shapley(index, old_rate)
        rounded = {player: _quantize(effects[player] * 100) for player in _PLAYERS}
        # 逐项四舍五入会产生残差；补给绝对影响最大的一项，保证归因合计仍等于差值。
        residual = delta - sum(rounded.values())
        if residual:
            target = max(_PLAYERS, key=lambda player: abs(effects[player]))
            rounded[target] += residual
        rows.append({
            "scope": scope, "group": label, "channel": channel, "program": program,
            "old_counts": f"{old_confirmed} / {old_total}",
            "new_counts": f"{new_confirmed} / {new_total}",
            "old_rate": f"{old_percent:.1f}%", "new_rate": f"{new_percent:.1f}%",
            "delta": _signed(delta),
            "churn": _signed(rounded[CHURN]),
            "assignment": _signed(rounded[ASSIGNMENT]),
            "confirmation": _signed(rounded[CONFIRMATION]),
            "delta_value": float(delta),
        })

    overall = rows[0]
    counts = [
        _column("group", "招生渠道"), _column("old_counts", "旧确认 / 受理"),
        _column("new_counts", "新确认 / 受理"), _column("old_rate", "旧转化率"),
        _column("new_rate", "新转化率"), _column("delta", "差值（百分点）"),
        _column("churn", "学员增减"), _column("assignment", "归属变动"),
        _column("confirmation", "确认变化"),
    ]
    cell_columns = [_column("channel", "招生渠道"), _column("program", "培训项目"), *counts[1:]]
    program_columns = [_column("group", "培训项目"), *counts[1:]]

    def table_rows(scope):
        return [{key: value for key, value in row.items() if key != "scope"} for row in rows if row["scope"] == scope]

    tables = [
        _table("渠道 × 项目差异归因", cell_columns, table_rows("组合")),
        _table("渠道合计差异归因", counts, table_rows("渠道")),
        _table("项目合计差异归因", program_columns, table_rows("项目")),
    ]
    metrics = [
        {"label": "旧转化率", "value": overall["old_rate"],
         "detail": f"{old_name} · {overall['old_counts'].replace(' / ', ' 人确认 / ')} 人受理"},
        {"label": "新转化率", "value": overall["new_rate"],
         "detail": f"{new_name} · {overall['new_counts'].replace(' / ', ' 人确认 / ')} 人受理"},
        {"label": "差值", "value": f"{overall['delta']} 百分点", "detail": "新转化率减旧转化率"},
        {"label": "学员增减", "value": overall["churn"], "detail": "新增与退出学员按各自批次归属和确认计"},
        {"label": "归属变动", "value": overall["assignment"], "detail": "共同学员的渠道或项目变化"},
        {"label": "确认变化", "value": overall["confirmation"], "detail": "共同学员的报名确认变化"},
    ]
    return {
        "state": "ok",
        "headline": f"{period} 两批受理学员对齐差异归因",
        "note": "三类变化按全部顺序试算后取平均，归因以百分点计并保留一位小数，合计等于新旧转化率之差。",
        "metrics": metrics,
        "tables": tables,
        "charts": [{
            "title": "各渠道 × 项目组合的转化率差值（百分点）", "kind": "bar",
            "series": [{"label": row["group"], "value": row["delta_value"]}
                       for row in rows if row["scope"] == "组合"],
        }],
        "sections": [
            {"title": "批次与口径", "text": (
                f"旧批次：{old_name}；新批次：{new_name}。统计月份 {period}。"
                "两批都按月报口径以学员编号去重，确认记录可以来自同月其他渠道。"
                "批次在发起时锁定，之后补传的新批次不参与本次在途计算。"
            )},
            {"title": "归因口径", "text": (
                "学员增减：退出学员按旧批次的归属与确认扣除，新增学员按新批次的归属与确认加入。"
                "归属变动：共同学员的渠道或项目按新批次调整。确认变化：共同学员的报名确认按新批次调整。"
                "三类变化按所有顺序逐一试算并取平均影响；空组合按零计。"
                "总体层面归属变动只重新分配学员、不改变确认与受理总数，因此通常净为零；"
                "渠道、项目和组合层面才体现迁移方向。"
                "逐项保留一位小数后，差额补给绝对影响最大的一项，保证归因之和等于页面上新旧转化率相减的值。"
            )},
        ],
    }
