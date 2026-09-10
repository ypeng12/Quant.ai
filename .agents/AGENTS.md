# Project Rules for Quant.ai

## Progress Reporting Style
Whenever providing updates or summarizing completed work to the user, ALWAYS structure the response using the following three mandatory sections:
1. **做了什么 (What I did)**
2. **修改了什么 (What was modified/changed)**
3. **打算做什么 (What I plan to do next)**

## Git Commit Style
Always format git commit messages like:
`feat(ai): fix grouping method and enhance prompt`

## Strict Prohibitions & Operational Rules
- **ABSOLUTELY NO FORCED-STOPPING THINKING (整个项目永久严禁任何强行停止交易的思维)**: NEVER add or introduce any forced-halt, lockout, or circuit breaker logic that blocks or pauses opening new trades (用户明确命令：整个项目永久禁止任何“强行停止交易、因亏损锁死标的、限制交易频率”的消极阻碍逻辑，无论任何时候都不允许加此类限制).
- **STRICT PROHIBITION ON HARDCODED RESTRICTIONS (永久严禁任何未经同意的硬编码限制)**: NEVER add hardcoded restrictions, veto filters, or artificial roadblocks (如午间时间锁、静态硬门槛、单指标一刀切否决等)，除非用户明确要求并同意。
- **MANDATORY PRIOR USER REVIEW BEFORE PUSHING `live_runner.py` (修改 live_runner 必须用户亲自审阅同意后方可 push)**: Before modifying and pushing any changes to `live_runner.py`, ALWAYS explicitly present the exact proposed logic changes to the user. You MUST wait for the user to review and explicitly approve before committing and pushing.

