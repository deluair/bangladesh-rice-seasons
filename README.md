# bangladesh-rice-seasons

Where Bangladesh grows each of its three rice crops, mapped at 20 m from Sentinel-1 radar for 2017, 2022 and 2023, and summed to 64 districts and 500+ upazilas.

Bangladesh plants rice three times a year. **Aus** goes in with the pre-monsoon rains (April to August), **Aman** is the monsoon crop (July to December) and **Boro** is the irrigated dry-season crop (January to May). The national statistics office (BBS) publishes district totals once a year, with a lag. This repository produces the same totals independently from satellite radar, which sees through monsoon cloud, and publishes the maps behind them.

## Results

| Season | Mapped area 2017 (ha) | 2022 (ha) | 2023 (ha) |
|---|---:|---:|---:|
| Aus | 2,269,672 | 1,678,819 | 1,758,175 |
| Aman | 4,290,560 | 3,881,200 | 4,124,876 |
| Boro | 4,726,679 | 4,844,697 | 4,515,677 |
| Any rice | 6,474,659 | 6,430,428 | 6,361,969 |

Areas cover the 13,985,088 ha inside the label footprint. District and upazila tables sum to the same national totals. All tables are in `results/`: `district_area_{year}.csv`, `upazila_area_{year}.csv`, `validation_{2022,2023}.csv`, `test_metrics.json`, `split.json`, `gap_summary.json`.

**Against BBS, by district (64 districts):**

| Map year | Season | BBS year | Map / BBS, national | Correlation across districts (r) | Median absolute district error |
|---|---|---|---:|---:|---:|
| 2022 | Boro | 2021-22 | 1.006 | 0.64 | 40% |
| 2023 | Boro | 2022-23 | 0.931 | 0.78 | 37% |
| 2022 | Aman | 2022-23 | 0.678 | 0.89 | 34% |
| 2022 | Aus | 2022-23 | 1.582 | 0.16 | 89% |

The Boro national total lands within 7% of BBS in both years. At district level the error is still large.

Aman follows the district pattern closely (r = 0.89) but undercounts by about a third.

Aus is not usable at district level. Its national total is 58% above BBS and its districts are uncorrelated with the official figures.

Aus and Aman for 2023 need the 2024 yearbook and are not compared.

## How it works

1. **Grid.** Bangladesh is cut into 0.2° tiles; every tile that touches the footprint of the 2017 label rasters is kept (413 tiles). Each tile is processed on a 20 m grid in UTM zone 46N (EPSG:32646).
2. **Radar.** Sentinel-1 radiometric-terrain-corrected backscatter (`sentinel-1-rtc`) from the Microsoft Planetary Computer, read anonymously. VV and VH are averaged to 20 m in linear power, converted to dB, and reduced to 30 median composites of 12 days per calendar year. Empty composites are filled by linear interpolation in time; the share of gap-filled pixels is recorded per tile-year.
3. **Labels.** The 2017 seasonal rice maps of Singha et al. (2019) are resampled from 10 m to the 20 m grid as the fraction of rice pixels; a 20 m pixel is rice when the fraction is at least 0.5. Pixels outside the label footprint (India, the Bay of Bengal) are excluded from training and evaluation.
4. **Model.** A small 1-D temporal CNN with three independent sigmoid outputs, one per season, since one field can carry two or three crops a year. It is trained on 2017 only. Tiles, not pixels, are split 80/10/10 into train, validation and test (seed 42), so no test pixel has a neighbour in training. A logistic regression on the same 60 inputs is the baseline. Input statistics are accumulated in float64.
5. **Thresholds.** With a 0.5 cut-off the CNN predicted Boro on 10.3% of test pixels against a 20.6% label rate. Each season's threshold is therefore chosen to maximise IoU on the validation tiles, then frozen; the test tiles are scored once with it.
6. **Maps and areas.** The 2017 model is applied to 2017, 2022 and 2023. Neighbouring tile grids overlap (a lat/lon box is rotated in UTM), so each pixel is counted only in the tile whose lat/lon cell contains its centre. Area is the pixel count times 0.04 ha divided by the UTM areal scale factor at the tile centre (1.002 to 1.006 across Bangladesh). Districts and upazilas are geoBoundaries ADM2 and ADM3 polygons.
7. **Validation.** District areas are compared with the printed season totals of the BBS *Yearbook of Agricultural Statistics 2023*.

## Details

**Test tiles (2017, 42 tiles, 33,623,081 pixels, scored once):**

| Model | Season | Threshold | Precision | Recall | F1 | IoU |
|---|---|---:|---:|---:|---:|---:|
| CNN | Aus | 0.25 | 0.497 | 0.641 | 0.560 | 0.389 |
| CNN | Aman | 0.40 | 0.741 | 0.792 | 0.766 | 0.620 |
| CNN | Boro | 0.30 | 0.474 | 0.726 | 0.574 | 0.402 |
| Logistic regression | Aus | 0.20 | 0.468 | 0.668 | 0.551 | 0.380 |
| Logistic regression | Aman | 0.30 | 0.711 | 0.732 | 0.721 | 0.564 |
| Logistic regression | Boro | 0.20 | 0.374 | 0.656 | 0.476 | 0.312 |

The CNN beats the baseline on every season. The margin is widest on Boro (IoU 0.40 vs 0.31) and narrowest on Aus.

Label rates on the test tiles are 9.3% (Aus), 26.5% (Aman) and 20.6% (Boro). The CNN predicts 12.0%, 28.4% and 31.6%, so it over-predicts Boro pixels in 2017.

**Gap filling (per-pixel figures, averaged over the 413 tiles):**

| Year | Pixels with at least one gap-filled composite | Empty 12-day composites per pixel (of 30) |
|---|---:|---:|
| 2017 | 100% | VV 0.54, VH 2.09 |
| 2022 | 1.2% | VV 0.31, VH 0.31 |
| 2023 | 39.6% | VV 0.84, VH 0.84 |

**BBS reference.** Only the "Total" rows of the yearbook's season tables are used, one per district and year. The district rows sum to the printed national totals within 5 ha:

| Season | BBS year | National total (ha) |
|---|---|---:|
| Aus | 2022-23 | 1,061,273 |
| Aman | 2022-23 | 5,724,822 |
| Boro | 2021-22 | 4,814,563 |
| Boro | 2022-23 | 4,852,290 |

Boro is harvested in April and May, so the 2022 Boro map is compared with BBS 2021-22.

**What this does not show.**
- The model is trained on one year (2017) and applied to later years without new labels. The 2022 and 2023 maps have no pixel-level check, only the district totals above.
- BBS district figures are themselves estimates. A gap between the map and BBS is not an error of the map alone.
- Some 2017 composites were read with a rasterio `NotGeoreferencedWarning`. Its source was not traced, and the composites were not spot-checked against an independent rebuild.

## Run it

```
uv sync
bash scripts/get_labels.sh labels_raw        # 3 label rasters, sha256-checked
uv run python -m ricemap.national --work work --labels-raw labels_raw \
    --bbs-csv data/bbs/district_rice_area.csv
```

Every stage skips outputs that already exist. `notebooks/national_run.ipynb` runs the same command on a Colab GPU VM. The full national run (413 tiles, three years) took about 7 h 10 min on a Colab A100 VM with 12 CPUs.

## Sources and licences

- **Sentinel-1 RTC**: Copernicus Sentinel data 2017, 2022, 2023, processed by ESA; RTC product by the Microsoft Planetary Computer (collection `sentinel-1-rtc`).
- **Seasonal rice labels, 2017**: Singha, M., Dong, J., Zhang, G., Xiao, X. (2019). High resolution paddy rice maps in cloud-prone Bangladesh and Northeast India using Sentinel-1 data. *Scientific Data* 6, 26. doi:10.1038/s41597-019-0036-3. Rasters: doi:10.6084/m9.figshare.7873157.v1, CC BY 4.0.
- **Administrative boundaries**: geoBoundaries gbOpen BGD ADM2 and ADM3, Creative Commons Attribution 3.0 Intergovernmental Organisations (CC BY 3.0 IGO), as returned by the geoBoundaries API.
- **District rice statistics**: Bangladesh Bureau of Statistics, *Yearbook of Agricultural Statistics 2023* (sha256 5ccf7615ce397b2d1f768146b022795001793e7ec2b3664dad55de9c2ebee1aa). Extracted to `data/bbs/district_rice_area.csv`; every table is checked against its printed national total in `data/bbs/CHECKS.md`.

Code: MIT.
