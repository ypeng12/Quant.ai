# L1 held-out horizon diagnostic

Status: complete; evaluated candidates: 100.
Evaluation kinds: intraday_diagnostic.

No trading PnL, model promotion, or live orders. Full-day trained artifacts were not reused.

Grid: exchange-calendar open anchored, fixed observation-clock intervals. Every candidate uses identical eligible rows.
Labels: first same-segment quote at/after decision+horizon within tolerance; training label maturity must precede cutoff.
Direction accuracy excludes zero targets and zero forecasts (abstentions); coverage and zero fractions are separate.
Metrics use future venue-mid marks, with MSE in bps²; IC is Pearson and rank IC is Spearman.

| Stock | Horizon | Model | Test rows | RMSE bps | IC | Rank IC | Direction accuracy |
|---|---|---|---:|---:|---:|---:|---:|
| SNDK | 1s | zero | 592 | 34.8692 | — | — | — |
| SNDK | 1s | past_mid_ridge | 592 | 33.6791 | 0.2676 | 0.2477 | 0.5359 |
| SNDK | 1s | qi_ridge | 592 | 34.8323 | 0.0060 | -0.0123 | 0.5087 |
| SNDK | 1s | l1_ridge | 592 | 34.1906 | 0.1817 | 0.1614 | 0.5612 |
| SNDK | 1s | past_mid_plus_l1_ridge | 592 | 33.1313 | 0.3126 | 0.2572 | 0.5883 |
| SNDK | 5s | zero | 489 | 41.4700 | — | — | — |
| SNDK | 5s | past_mid_ridge | 489 | 38.8023 | 0.3538 | 0.2841 | 0.5822 |
| SNDK | 5s | qi_ridge | 489 | 41.5092 | 0.0331 | 0.0276 | 0.5091 |
| SNDK | 5s | l1_ridge | 489 | 41.1767 | 0.1221 | 0.0222 | 0.4932 |
| SNDK | 5s | past_mid_plus_l1_ridge | 489 | 38.6055 | 0.3669 | 0.2681 | 0.5868 |
| SNDK | 30s | zero | 455 | 42.0828 | — | — | — |
| SNDK | 30s | past_mid_ridge | 455 | 38.7488 | 0.3898 | 0.3368 | 0.5981 |
| SNDK | 30s | qi_ridge | 455 | 42.0175 | 0.0159 | 0.0248 | 0.5225 |
| SNDK | 30s | l1_ridge | 455 | 41.8857 | 0.0773 | 0.1307 | 0.5296 |
| SNDK | 30s | past_mid_plus_l1_ridge | 455 | 39.2236 | 0.3616 | 0.3076 | 0.6028 |
| SNDK | 1min | zero | 468 | 43.8905 | — | — | — |
| SNDK | 1min | past_mid_ridge | 468 | 39.2528 | 0.4643 | 0.3962 | 0.6157 |
| SNDK | 1min | qi_ridge | 468 | 43.9197 | -0.0120 | -0.0108 | 0.4944 |
| SNDK | 1min | l1_ridge | 468 | 43.3672 | 0.1953 | 0.2057 | 0.5528 |
| SNDK | 1min | past_mid_plus_l1_ridge | 468 | 39.2141 | 0.4621 | 0.4043 | 0.6427 |
| SNDK | 5min | zero | 418 | 46.4182 | — | — | — |
| SNDK | 5min | past_mid_ridge | 418 | 45.4582 | 0.4357 | 0.4378 | 0.5379 |
| SNDK | 5min | qi_ridge | 418 | 46.6635 | 0.0353 | 0.0508 | 0.4597 |
| SNDK | 5min | l1_ridge | 418 | 47.1745 | 0.0280 | 0.0143 | 0.4645 |
| SNDK | 5min | past_mid_plus_l1_ridge | 418 | 46.2810 | 0.1963 | 0.1837 | 0.4694 |
| TSLA | 1s | zero | 905 | 13.8614 | — | — | — |
| TSLA | 1s | past_mid_ridge | 905 | 12.5374 | 0.4325 | 0.3594 | 0.5825 |
| TSLA | 1s | qi_ridge | 905 | 13.9338 | -0.0948 | -0.0928 | 0.4795 |
| TSLA | 1s | l1_ridge | 905 | 13.8089 | 0.0906 | 0.0513 | 0.5021 |
| TSLA | 1s | past_mid_plus_l1_ridge | 905 | 12.7070 | 0.4003 | 0.2706 | 0.5726 |
| TSLA | 5s | zero | 891 | 14.8213 | — | — | — |
| TSLA | 5s | past_mid_ridge | 891 | 13.8346 | 0.4320 | 0.3479 | 0.5491 |
| TSLA | 5s | qi_ridge | 891 | 15.2566 | -0.1063 | -0.1060 | 0.4832 |
| TSLA | 5s | l1_ridge | 891 | 15.3906 | 0.1024 | 0.1082 | 0.5207 |
| TSLA | 5s | past_mid_plus_l1_ridge | 891 | 14.3441 | 0.3595 | 0.3190 | 0.5659 |
| TSLA | 30s | zero | 842 | 17.2674 | — | — | — |
| TSLA | 30s | past_mid_ridge | 842 | 16.1898 | 0.4061 | 0.3464 | 0.5927 |
| TSLA | 30s | qi_ridge | 842 | 18.0689 | 0.1094 | 0.1104 | 0.5150 |
| TSLA | 30s | l1_ridge | 842 | 17.2425 | 0.1958 | 0.1739 | 0.5125 |
| TSLA | 30s | past_mid_plus_l1_ridge | 842 | 16.0968 | 0.4108 | 0.3574 | 0.5902 |
| TSLA | 1min | zero | 809 | 18.2133 | — | — | — |
| TSLA | 1min | past_mid_ridge | 809 | 16.9012 | 0.4337 | 0.3897 | 0.5957 |
| TSLA | 1min | qi_ridge | 809 | 18.6271 | 0.0919 | 0.1300 | 0.5164 |
| TSLA | 1min | l1_ridge | 809 | 19.2093 | 0.1044 | 0.1477 | 0.5680 |
| TSLA | 1min | past_mid_plus_l1_ridge | 809 | 18.3092 | 0.2907 | 0.3006 | 0.6096 |
| TSLA | 5min | zero | 767 | 19.6648 | — | — | — |
| TSLA | 5min | past_mid_ridge | 767 | 19.7776 | 0.3714 | 0.3642 | 0.6199 |
| TSLA | 5min | qi_ridge | 767 | 21.3291 | 0.1154 | 0.1088 | 0.5192 |
| TSLA | 5min | l1_ridge | 767 | 21.5223 | 0.0029 | 0.0503 | 0.5166 |
| TSLA | 5min | past_mid_plus_l1_ridge | 767 | 19.3722 | 0.3538 | 0.3497 | 0.6371 |
| PLTR | 1s | zero | 1029 | 22.5255 | — | — | — |
| PLTR | 1s | past_mid_ridge | 1029 | 21.1265 | 0.3745 | 0.3209 | 0.5899 |
| PLTR | 1s | qi_ridge | 1029 | 22.5045 | 0.1461 | 0.1715 | 0.5410 |
| PLTR | 1s | l1_ridge | 1029 | 25.1171 | 0.1313 | 0.1093 | 0.5397 |
| PLTR | 1s | past_mid_plus_l1_ridge | 1029 | 22.0283 | 0.3516 | 0.3201 | 0.6164 |
| PLTR | 5s | zero | 942 | 24.5029 | — | — | — |
| PLTR | 5s | past_mid_ridge | 942 | 22.0262 | 0.4453 | 0.3778 | 0.6064 |
| PLTR | 5s | qi_ridge | 942 | 26.6300 | 0.1130 | 0.1113 | 0.5314 |
| PLTR | 5s | l1_ridge | 942 | 30.0931 | 0.1004 | -0.0027 | 0.5105 |
| PLTR | 5s | past_mid_plus_l1_ridge | 942 | 25.9635 | 0.3258 | 0.2919 | 0.5879 |
| PLTR | 30s | zero | 905 | 26.0755 | — | — | — |
| PLTR | 30s | past_mid_ridge | 905 | 23.6802 | 0.4295 | 0.3799 | 0.6148 |
| PLTR | 30s | qi_ridge | 905 | 26.1396 | 0.1398 | 0.1326 | 0.5341 |
| PLTR | 30s | l1_ridge | 905 | 29.6469 | 0.1389 | 0.1751 | 0.5739 |
| PLTR | 30s | past_mid_plus_l1_ridge | 905 | 24.3438 | 0.3955 | 0.3591 | 0.5977 |
| PLTR | 1min | zero | 887 | 26.2374 | — | — | — |
| PLTR | 1min | past_mid_ridge | 887 | 24.0333 | 0.4080 | 0.3640 | 0.5938 |
| PLTR | 1min | qi_ridge | 887 | 26.1313 | 0.1531 | 0.1370 | 0.5206 |
| PLTR | 1min | l1_ridge | 887 | 27.8793 | 0.1484 | 0.1596 | 0.5641 |
| PLTR | 1min | past_mid_plus_l1_ridge | 887 | 24.5937 | 0.3686 | 0.3471 | 0.6053 |
| PLTR | 5min | zero | 856 | 29.8795 | — | — | — |
| PLTR | 5min | past_mid_ridge | 856 | 27.9763 | 0.3645 | 0.3186 | 0.5550 |
| PLTR | 5min | qi_ridge | 856 | 33.5534 | -0.1446 | -0.1197 | 0.4578 |
| PLTR | 5min | l1_ridge | 856 | 30.9842 | -0.0710 | -0.0426 | 0.4766 |
| PLTR | 5min | past_mid_plus_l1_ridge | 856 | 30.6096 | 0.1745 | 0.1439 | 0.5094 |
| NVDA | 1s | zero | 2680 | 1.9016 | — | — | — |
| NVDA | 1s | past_mid_ridge | 2680 | 1.7860 | 0.3585 | 0.2412 | 0.6021 |
| NVDA | 1s | qi_ridge | 2680 | 2.0081 | 0.0019 | 0.0182 | 0.5247 |
| NVDA | 1s | l1_ridge | 2680 | 2.0958 | -0.3045 | -0.0744 | 0.4549 |
| NVDA | 1s | past_mid_plus_l1_ridge | 2680 | 1.8532 | 0.2819 | 0.1982 | 0.5828 |
| NVDA | 5s | zero | 2675 | 2.3428 | — | — | — |
| NVDA | 5s | past_mid_ridge | 2675 | 2.2805 | 0.3259 | 0.1663 | 0.5557 |
| NVDA | 5s | qi_ridge | 2675 | 2.5266 | -0.0096 | -0.0053 | 0.4977 |
| NVDA | 5s | l1_ridge | 2675 | 2.4719 | -0.3157 | -0.0829 | 0.4827 |
| NVDA | 5s | past_mid_plus_l1_ridge | 2675 | 2.2834 | 0.2822 | 0.1541 | 0.5544 |
| NVDA | 30s | zero | 2674 | 3.5845 | — | — | — |
| NVDA | 30s | past_mid_ridge | 2674 | 3.5311 | 0.2118 | 0.0768 | 0.5273 |
| NVDA | 30s | qi_ridge | 2674 | 3.7654 | -0.0189 | -0.0015 | 0.5184 |
| NVDA | 30s | l1_ridge | 2674 | 3.7168 | -0.2004 | -0.0552 | 0.4843 |
| NVDA | 30s | past_mid_plus_l1_ridge | 2674 | 3.6199 | 0.1200 | 0.0525 | 0.5149 |
| NVDA | 1min | zero | 2666 | 4.5127 | — | — | — |
| NVDA | 1min | past_mid_ridge | 2666 | 4.4891 | 0.1550 | 0.0702 | 0.5338 |
| NVDA | 1min | qi_ridge | 2666 | 4.5596 | -0.0021 | -0.0027 | 0.5119 |
| NVDA | 1min | l1_ridge | 2666 | 4.6255 | -0.1351 | -0.0388 | 0.5111 |
| NVDA | 1min | past_mid_plus_l1_ridge | 2666 | 4.5585 | 0.0997 | 0.0487 | 0.5353 |
| NVDA | 5min | zero | 2618 | 8.6763 | — | — | — |
| NVDA | 5min | past_mid_ridge | 2618 | 8.6681 | 0.1077 | 0.0851 | 0.5487 |
| NVDA | 5min | qi_ridge | 2618 | 8.6690 | -0.0119 | -0.0092 | 0.5206 |
| NVDA | 5min | l1_ridge | 2618 | 8.7257 | -0.0167 | -0.0086 | 0.5529 |
| NVDA | 5min | past_mid_plus_l1_ridge | 2618 | 8.7068 | 0.0816 | 0.0486 | 0.5884 |

## Interpretation limits

- Future feed-mid marks are not executable returns or trading PnL.
- IEX is one venue; spreads and future-mid marks are not consolidated NBBO.
- Historical timestamps cannot verify arrival latency or attainable fills.
- One-day morning/afternoon splits are intraday diagnostics, not future-session validation.
- Long-horizon labels overlap on the decision grid; rows are serially dependent, not independent trials.
- Quote-only study: signed trades, state-transition microprice, bar-alpha fusion and execution are not tested here.
- 2/5 bps are hypothetical one-way costs; sign-change statistics are not realized turnover or savings.
- No candidate or horizon is selected for live trading or optimized against test profit.
