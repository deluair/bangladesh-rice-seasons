# Validation Checks: BBS Yearbook of Agricultural Statistics 2023

This document records the verification check for each extracted rice area and production table.
Numbers were copied directly from the PDF text (`pdftotext -layout` / PDF text layer).
For each table, the 64 district rows are summed and compared against the printed national total (`Bangladesh`).

| Table | Year | Metric | Printed Total | Summed Total | Difference | Notes |
|---|---|---|---|---|---|---|
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2021-22 | area_acres | 248,505.0 | 248,505.0 | +0.0 | Exact match |
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2021-22 | area_ha | 100,569.0 | 100,569.0 | +0.0 | Exact match |
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2021-22 | production_mt | 131,421.0 | 131,424.0 | +3.0 | Rounding difference in district sum (+3.0) |
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2022-23 | area_acres | 209,921.0 | 209,921.0 | +0.0 | Exact match |
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2022-23 | area_ha | 84,954.0 | 84,955.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3.1 Estimates of Aus (Local), 2021-22 To 2022-23. | 2022-23 | production_mt | 122,148.0 | 122,143.0 | -5.0 | Rounding difference in district sum (-5.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2021-22 | area_acres | 2,615,582.0 | 2,615,583.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2021-22 | area_ha | 1,058,511.0 | 1,058,513.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2021-22 | production_mt | 2,869,436.0 | 2,869,435.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2022-23 | area_acres | 2,412,484.0 | 2,412,485.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2022-23 | area_ha | 976,319.0 | 976,313.0 | -6.0 | Discrepancy (-6.0) |
| Table: 3.2 Estimates of Aus (HYV), 2021-22 to 2022-23. | 2022-23 | production_mt | 2,779,007.0 | 2,779,009.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2021-22 | area_acres | 2,864,087.0 | 2,864,086.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2021-22 | area_ha | 1,159,080.0 | 1,159,081.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2021-22 | production_mt | 3,000,857.0 | 3,000,855.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2022-23 | area_acres | 2,622,404.0 | 2,622,406.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2022-23 | area_ha | 1,061,273.0 | 1,061,268.0 | -5.0 | Rounding difference in district sum (-5.0) |
| Table: 3. 3 Estimates of Aus (TOTAL=LOCAL + HYV), 2021-22 To 2022-23. | 2022-23 | production_mt | 2,901,156.0 | 2,901,159.0 | +3.0 | Rounding difference in district sum (+3.0) |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2021-22 | area_acres | 614,084.0 | 614,084.0 | +0.0 | Exact match |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2021-22 | area_ha | 248,528.0 | 248,529.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2021-22 | production_mt | 271,791.0 | 271,789.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2022-23 | area_acres | 541,716.0 | 541,776.0 | +60.0 | District sum rounding/misprint in BBS source table (+60.0) |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2022-23 | area_ha | 219,264.0 | 219,266.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table 1: Estimates of Broadcast Aman, 2021-22 to 2022-23. | 2022-23 | production_mt | 240,642.0 | 240,641.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2021-22 | area_acres | 1,785,670.0 | 1,785,671.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2021-22 | area_ha | 722,663.0 | 722,665.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2021-22 | production_mt | 1,107,786.0 | 1,107,786.0 | +0.0 | Exact match |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2022-23 | area_acres | 1,695,485.0 | 1,695,485.0 | +0.0 | Exact match |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2022-23 | area_ha | 686,164.0 | 686,164.0 | +0.0 | Exact match |
| Table: 3.2 Estimates of Transplant Aman (L.T), 2021-22 to 2022-23. | 2022-23 | production_mt | 1,130,454.0 | 1,130,457.0 | +3.0 | Rounding difference in district sum (+3.0) |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2021-22 | area_acres | 11,732,031.0 | 11,607,708.0 | -124,323.0 | Discrepancy (-124323.0) |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2021-22 | area_ha | 4,748,936.0 | 4,748,934.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2021-22 | production_mt | 13,578,813.0 | 13,578,813.0 | +0.0 | Exact match |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2022-23 | area_acres | 11,906,085.0 | 11,906,086.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2022-23 | area_ha | 4,819,394.0 | 4,819,393.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: .3.3 Estimates of High Yielding Variety (HYV) Aman, 2021-22 to 2022-23. | 2022-23 | production_mt | 14,055,299.0 | 14,055,297.5 | -1.5 | Rounding difference in district sum (-1.5) |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2021-22 | area_acres | 14,131,786.0 | 14,131,786.0 | +0.0 | Exact match |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2021-22 | area_ha | 5,720,127.0 | 5,720,126.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2021-22 | production_mt | 14,958,390.0 | 14,958,391.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2022-23 | area_acres | 14,143,347.0 | 14,143,347.0 | +0.0 | Exact match |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2022-23 | area_ha | 5,724,822.0 | 5,724,821.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table:3. 4 Estimates of Total Aman (Broadcast+L.T + HYV) Aman, 2021-22 to 2022-23. | 2022-23 | production_mt | 15,426,395.0 | 15,426,395.0 | +0.0 | Exact match |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2021-22 | area_acres | 61,175.0 | 61,175.0 | +0.0 | Exact match |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2021-22 | area_ha | 24,759.0 | 24,760.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2021-22 | production_mt | 45,478.0 | 45,476.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2022-23 | area_acres | 60,657.0 | 60,658.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2022-23 | area_ha | 24,549.0 | 24,550.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 1 Estimates of Local Boro, 2021-22 to 2022-23. | 2022-23 | production_mt | 46,790.0 | 46,791.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2021-22 | area_acres | 9,027,557.0 | 9,027,557.0 | +0.0 | Exact match |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2021-22 | area_ha | 3,653,623.0 | 3,653,622.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2021-22 | production_mt | 14,823,141.0 | 14,823,140.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2022-23 | area_acres | 8,943,493.0 | 8,943,493.0 | +0.0 | Exact match |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2022-23 | area_ha | 3,619,599.0 | 3,619,599.0 | +0.0 | Exact match |
| Table: 2 Estimates of HYV Boro, 2021-22 to 2022-23. | 2022-23 | production_mt | 14,984,750.0 | 14,984,748.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2021-22 | area_acres | 2,807,230.0 | 2,807,230.0 | +0.0 | Exact match |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2021-22 | area_ha | 1,136,181.0 | 1,136,182.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2021-22 | production_mt | 5,317,326.0 | 5,317,326.0 | +0.0 | Exact match |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2022-23 | area_acres | 2,985,024.0 | 2,985,023.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2022-23 | area_ha | 1,208,142.0 | 1,208,141.0 | -1.0 | Rounding difference in district sum (-1.0) |
| Table: 3 Estimates of Hybrid Boro, 2021-22 to 2022-23. | 2022-23 | production_mt | 5,736,086.0 | 5,736,089.0 | +3.0 | Rounding difference in district sum (+3.0) |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2021-22 | area_acres | 11,895,962.0 | 11,895,963.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2021-22 | area_ha | 4,814,563.0 | 4,814,564.0 | +1.0 | Rounding difference in district sum (+1.0) |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2021-22 | production_mt | 20,185,945.0 | 20,185,943.0 | -2.0 | Rounding difference in district sum (-2.0) |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2022-23 | area_acres | 11,989,174.0 | 11,989,176.0 | +2.0 | Rounding difference in district sum (+2.0) |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2022-23 | area_ha | 4,852,290.0 | 4,852,290.0 | +0.0 | Exact match |
| Table: 4 Estimates of Total Boro (Local+HYV+Hybrid), 2021-22 to 2022-23. | 2022-23 | production_mt | 20,767,626.0 | 20,767,623.0 | -3.0 | Rounding difference in district sum (-3.0) |
