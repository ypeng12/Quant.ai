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
- **MANDATORY PRIOR CONSULTATION BEFORE MODIFYING `live_runner.py` (修改 live_runner 前必须先咨询确认)**: Before modifying `live_runner.py`, ALWAYS explicitly explain what you want to do to the user and obtain explicit permission before writing or changing any code.
