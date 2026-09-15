# Global city outdoor-comfort ranking

How many daylight hours a year is it thermally comfortable to be outdoors,
walking around or going for a casual run?

Generated 2026-09-15 from 1906 scored cities
(1904 eligible for the ranking, subset `all`), UTCI over
2010-2024.

**Read the sensitivity section before quoting a rank.** Several of the choices
below move cities by tens of places, and the ranking is only meaningful
alongside the assumptions that produced it.

## Method

1. **Cities** — JRC GHS-UCDB R2024A urban centres, population >= 300,000.
   Urban centres rather than administrative units: admin boundaries are not
   internationally comparable (Chongqing's municipality is 82,000 km2 of mostly
   mountain).
2. **UTCI** — hourly Universal Thermal Climate Index at the nearest ERA5 cell.
3. **Daylight** — solar elevation at the hour's midpoint above
   -6.0 deg, via `pvlib`. Elevation rather than
   sunrise/sunset times, so polar day and polar night degrade gracefully
   instead of raising.
4. **Comfort weight** — a graded trapezoid over UTCI, not a binary cutoff. A
   cutoff would make the ranking a function of where the threshold lands
   rather than of the climate.

   Active profile: **walking** — weight 0 at 3.0 degC, rising to 1 at
   9.0 degC, holding to 26.0 degC, falling to 0 at 32.0 degC.

   UTCI's reference person walks at 4 km/h (2.3 MET), so the published "no
   thermal stress" band of 9-26 degC already describes walking and is used as
   published. `sitting` (12-24) and `running` (5-22) are alternative profiles;
   the running band is a documented heuristic, since UTCI is not defined above
   2.3 MET.
5. **Penalties** — precipitation per hour (1.0 dry, 0.3 light,
   0.0 above 1.0 mm/h); annual mean PM2.5 as a scalar on the city
   total. Wind is *not* penalised separately: UTCI is already a function of
   10 m wind speed, and a second term would double-count it.

## Sun exposure

`exposure.sun_fraction` is **0.5** — half the daylight hour in direct
sun, half in shade.

This moves the *score* more than any other parameter, and the *ranking* less
than you would expect. Going from full sun to full shade changes some cities'
comfort hours by well over 100%, but it moves most cities in the same direction
for their latitude, so relative order is partly preserved. The air-quality
penalty and the choice of headline metric both reorder the table more than
exposure does — see the sensitivity table. Both facts matter: quoting an
absolute hours figure without stating the exposure is meaningless, while a rank
is more robust to it than to the AQ decision.

UTCI's reference person is unshaded. In an equatorial or subtropical city the
sun is what makes being outside unpleasant — mean radiant temperature runs
45-60 degC under a near-vertical sun even where the air is 24 degC. At high
latitude the sun is the only thing making a 7 degC afternoon bearable. The two
cases pull in opposite directions, so a single fixed exposure hides the effect
rather than resolving it.

0.5 is not a measurement. Street geometry, tree canopy and building shadow vary
enormously between cities and are not modelled. Half sun is an admission of
that. Shade is approximated by clamping mean radiant temperature to air
temperature; real shade sits slightly below that under open sky and above it
beside a sun-warmed wall.

Both extremes are carried per city as `comfort_hours_sun` and
`comfort_hours_shade`.

Most sun-sensitive cities in this run:

| City | Full sun | Full shade | Δ |
|---|---:|---:|---:|
| Zamboanga City | 385 | 1,431 | +271% |
| Kannur | 488 | 1,742 | +257% |
| Mangaluru | 504 | 1,750 | +247% |
| Kollam | 526 | 1,784 | +239% |
| Reykjavik | 1,615 | 1,055 | -35% |
| Brighton | 2,383 | 1,636 | -31% |
| Oruro | 3,288 | 2,266 | -31% |
| Liverpool | 2,301 | 1,685 | -27% |

## The five metrics are five different questions

| Column | Question |
|---|---|
| `comfort_hours_yr` | How much comfortable daylight is there in a year? **Primary.** |
| `comfort_fraction` | What share of daylight is comfortable? |
| `worst_month_hours` | How bad does the floor get? |
| `evenness_factor` | Is it spread across the year or concentrated? |
| `longest_bad_streak_days` | What is the longest unbroken bad stretch? |

They disagree, and the disagreement is the point. Moscow banks 1,676 comfortable
hours on the primary metric and has a worst month of zero with a 141-day
unbroken bad run; it is simultaneously mid-table and near-last depending on
which question you asked.

`comfort_fraction` **systematically flatters high-latitude cities**: their worst
hours are the dark ones, which never enter the denominator. Reykjavik's January
is almost entirely excluded from Reykjavik's own score.

`evenness_factor` is always 0-to-1 with higher meaning more even.
`evenness_stat` is the underlying statistic and its direction depends on
`metrics.evenness` — normalised entropy rises with evenness, coefficient of
variation falls. **The default is `cv`.** Shannon entropy over 12 monthly
shares is structurally insensitive to a dead season: Moscow scores zero
comfortable hours in December and January and still scores 0.80 of 1.0 under
Shannon, against 0.11 under CV.

Composite: `comfort_hours_yr x evenness_factor x aq_factor`. Multiplicative
because the three are veto-like. Every component stays in the CSV so a reader
who disagrees with the weighting can rebuild the ranking without rerunning.

## Ranking

| # | City | Country | Hours/yr | Sun | Shade | Frac | Worst mo | Bad run | Even | PM2.5 | AQ | Composite | Flags |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | Iquique | Chile | 4,472 | 2,733 | 4,718 | 0.94 | 315 | 0 | 0.92 | – | 1.00 | 4,134 | coast+rel |
| 2 | Tacna | Peru | 4,408 | 3,193 | 4,560 | 0.94 | 314 | 0 | 0.93 | 7.0 | 1.00 | 4,114 | relief |
| 3 | Antofagasta | Chile | 4,632 | 3,885 | 4,699 | 0.98 | 331 | 0 | 0.91 | 11.6 | 0.96 | 4,070 | coast+rel |
| 4 | Dessie | Ethiopia | 4,057 | 3,390 | 4,115 | 0.87 | 300 | 1 | 0.95 | – | 1.00 | 3,836 | relief |
| 5 | Santa Cruz de Tenerife | Spain | 4,434 | 4,315 | 4,280 | 0.93 | 285 | 3 | 0.87 | 8.5 | 1.00 | 3,836 | ref coast+rel |
| 6 | Las Palmas de Gran Canaria | Spain | 4,338 | 4,043 | 4,297 | 0.91 | 283 | 2 | 0.88 | 9.4 | 1.00 | 3,810 | ref coast+rel |
| 7 | Pachuca | México | 3,847 | 3,374 | 3,894 | 0.82 | 281 | 1 | 0.95 | 9.7 | 1.00 | 3,658 | relief |
| 8 | Lima | Peru | 4,360 | 3,568 | 4,496 | 0.94 | 278 | 0 | 0.89 | 13.0 | 0.93 | 3,642 | coast+rel |
| 9 | Sana'a | Yemen | 4,087 | 2,957 | 4,350 | 0.86 | 309 | 1 | 0.95 | 13.2 | 0.93 | 3,623 | relief |
| 10 | Honolulu | United States | 4,124 | 3,278 | 4,434 | 0.88 | 296 | 2 | 0.88 | 7.6 | 1.00 | 3,611 | coast+rel |
| 11 | Safi | Morocco | 4,242 | 3,773 | 4,308 | 0.89 | 281 | 2 | 0.85 | 8.0 | 1.00 | 3,601 | coast |
| 12 | Nakuru | Kenya | 3,979 | 2,896 | 4,213 | 0.84 | 296 | 1 | 0.94 | 11.8 | 0.96 | 3,596 | relief |
| 13 | Dhamar | Yemen | 4,261 | 3,756 | 4,244 | 0.90 | 311 | 1 | 0.92 | 14.0 | 0.91 | 3,587 | relief |
| 14 | Aguascalientes | México | 3,819 | 2,927 | 4,182 | 0.81 | 275 | 1 | 0.93 | 7.1 | 1.00 | 3,547 | relief |
| 15 | San Luis Potosí | México | 3,798 | 3,103 | 4,006 | 0.81 | 288 | 2 | 0.93 | 6.6 | 1.00 | 3,541 | relief |
| 16 | Durango | México | 3,805 | 3,052 | 3,976 | 0.80 | 276 | 2 | 0.93 | 5.4 | 1.00 | 3,528 | relief |
| 17 | Tijuana | México | 4,413 | 4,122 | 4,368 | 0.93 | 282 | 4 | 0.84 | 12.5 | 0.94 | 3,495 | coast+rel |
| 18 | Mission Viejo | United States | 4,407 | 3,868 | 4,461 | 0.92 | 289 | 2 | 0.84 | 12.9 | 0.93 | 3,456 | coast+rel |
| – | Funchal | Portugal | 4,070 | 3,547 | 4,138 | 0.86 | 272 | 2 | 0.84 | 8.9 | 1.00 | 3,430 | <floor ref coast+rel |
| 19 | Kenitra | Morocco | 3,963 | 3,366 | 4,212 | 0.83 | 273 | 2 | 0.87 | 10.1 | 1.00 | 3,424 | coast |
| 20 | Jijiga | Ethiopia | 3,774 | 2,854 | 4,261 | 0.81 | 268 | 1 | 0.88 | 8.4 | 1.00 | 3,323 | relief |
| 21 | Querétaro | México | 3,615 | 2,777 | 4,036 | 0.77 | 258 | 2 | 0.92 | 8.6 | 1.00 | 3,308 | relief |
| 22 | Valparaíso | Chile | 4,268 | 4,284 | 3,954 | 0.90 | 243 | 2 | 0.80 | 11.4 | 0.97 | 3,297 | coast+rel |
| 23 | Hargeisa | Somalia | 3,755 | 2,934 | 4,287 | 0.80 | 252 | 1 | 0.88 | 8.6 | 1.00 | 3,286 |  |
| 24 | Polokwane | South Africa | 3,571 | 2,891 | 3,954 | 0.76 | 248 | 1 | 0.91 | 8.2 | 1.00 | 3,259 |  |
| 25 | Cochabamba | Bolivia | 3,724 | 2,819 | 3,852 | 0.79 | 216 | 1 | 0.87 | 5.9 | 1.00 | 3,248 | relief |
| 26 | Puebla | México | 3,798 | 2,995 | 3,921 | 0.82 | 269 | 1 | 0.93 | 13.6 | 0.92 | 3,247 | relief |
| 27 | Morelia | México | 3,585 | 2,613 | 4,029 | 0.76 | 265 | 1 | 0.91 | 10.5 | 0.99 | 3,245 | relief |
| 28 | Saltillo | México | 3,500 | 2,640 | 3,948 | 0.74 | 263 | 2 | 0.92 | 9.6 | 1.00 | 3,223 | relief |
| 29 | Perth | Australia | 3,772 | 3,459 | 3,822 | 0.80 | 239 | 2 | 0.85 | 6.2 | 1.00 | 3,214 | coast |
| 114 | Valencia | Spain | 3,429 | 2,994 | 3,718 | 0.71 | 178 | 4 | 0.76 | 8.7 | 1.00 | 2,596 | ref coast |

## Sensitivity

Kendall's tau against the baseline ranking. Low tau means the variant asks a
materially different question; a city whose rank survives every variant is a
real result, and one that moves is an artefact of the thresholds.

| Variant | Kendall tau | Mean rank change | Max rank change |
|---|---:|---:|---:|
| `metric_raw_hours` | 0.541 | 321.0 | 1070 |
| `metric_fraction` | 0.553 | 311.7 | 1062 |
| `metric_worst_month` | 0.625 | 250.9 | 959 |
| `profile_running` | 0.642 | 247.5 | 1202 |
| `evenness_shannon` | 0.741 | 175.9 | 1176 |
| `aq_penalty_off` | 0.759 | 175.2 | 736 |
| `band_warm_+2C` | 0.791 | 146.8 | 580 |
| `band_cool_-2C` | 0.796 | 142.8 | 734 |
| `exposure_0` | 0.797 | 145.9 | 612 |
| `exposure_1` | 0.832 | 119.4 | 624 |
| `rain_penalty_off` | 0.888 | 77.7 | 1155 |
| `profile_sitting` | 0.893 | 77.6 | 694 |
| `exposure_0.25` | 0.900 | 71.7 | 322 |
| `exposure_0.75` | 0.909 | 64.6 | 324 |
| `daylight_sunrise_0deg` | 0.933 | 46.4 | 401 |
| `elevation_correction_off` | 0.966 | 22.0 | 465 |
| `baseline` | 1.000 | 0.0 | 0 |

Least stable cities — their position is a statement about the parameters, not
about the climate:

| City | Rank volatility (sd) | Median rank |
|---|---:|---:|
| Oslo | 452.1 | 1489 |
| Stockholm | 430.8 | 1816 |
| Gothenburg | 407.2 | 1576 |
| Irkutsk | 400.4 | 1651 |
| Malmo | 399.9 | 1722 |
| Kaliningrad | 397.8 | 1411 |
| Copenhagen | 394.7 | 1662 |
| Vitsebsk | 391.8 | 1777 |

## Known limitations

- **ERA5 misses persistent coastal stratocumulus, and it puts Lima at number
  one.** ERA5 gives Lima 3,276 sunshine hours a year (direct beam over
  120 W/m2). Ground observation for Lima is about 1,230-1,300 — a factor of
  2.5. The 0.25 deg grid does not resolve the shallow marine stratocumulus deck
  that produces Lima's *garua*, so the reanalysis sees a sunny coastal desert
  where residents see eight grey months. The same proxy reproduces San
  Francisco (3,081 against a published ~3,060) and Barcelona (2,796 against
  ~2,590) closely, so this is specific to persistent stratocumulus regimes
  rather than a general bias: suspect every west-coast subtropical city under a
  cold current — coastal Peru and northern Chile above all, and to a lesser
  degree Namibia and Angola. Lima, Chiclayo, Trujillo and Valparaiso should be
  read with that in mind, and Lima's rank in particular should not be quoted
  without it.
- **No sunshine or gloom term at all.** The metric scores thermal comfort,
  rain and air quality. A city that is permanently overcast at 20 degC scores
  as well as one that is sunny at 20 degC, and in the shade-weighted default it
  can score *better*, because cloud suppresses the mean radiant temperature
  that would otherwise push a warm city past the top of the band. Whatever
  ERA5's cloud errors, this is a modelling choice worth knowing: for many
  people "grey but mild" and "bright and mild" are not the same offer.
- **31 km grid: no urban heat island, no coastal microclimate.** The ERA5 cell
  is the city's surroundings, not the city. 953 of 1906 scored
  cities carry `microclimate_risk`. That base rate is high enough to need its
  own caveat — most large cities are coastal, so the flag marks "treat with
  suspicion", not "unusual".
- **Centroids are urban-centre centroids.** For polycentric conurbations this
  lands somewhere no one would call the city: the Bay Area urban centre sits at
  37.58, -122.10, in the inland East Bay, so "San Francisco" here describes
  Hayward's climate rather than the peninsula's. Lima and Vancouver have the
  same problem in the other direction.
- **UTCI assumes seasonally adapted clothing and a walking reference person.**
  It does not model acclimatisation, and a Finn and a Nigerian do not agree on
  15 degC.
- **Shade is modelled crudely** — see the exposure section. There is no tree
  canopy, no street-canyon geometry, no awnings.
- **PM2.5 is CAMS**, point-extracted, 10.0-to-55.0 ug/m3 mapped
  onto the penalty. Against ground monitors CAMS tends to underestimate in
  South Asia and over-smooth urban-rural gradients — Delhi reads 71 here
  against measured annual means nearer 100. Cities near the penalty floor are
  where the choice of product could move the ranking.
- **Precipitation is a cell mean over ~31 km**, so it smears a convective
  downpour across an area far larger than the shower: the wet tropics look more
  drizzly and less torrential than they are.
- **No pollen, no mosquito load, no daylight-length preference, no noise, no
  air-conditioning of the indoor alternative, no safety, no seasonal PM2.5.**

## Reproducing

```bash
uv sync
uv run cli.py fetch-cities
uv run cli.py fetch-utci --validation
uv run cli.py fetch-aq --validation
uv run cli.py score --top 30
uv run cli.py sweep --validation
uv run cli.py report
uv run cli.py export-agent
```

`export-agent` writes `out/agent/`: the hourly cache re-aggregated into a
1 degC UTCI histogram per city, month, light (day / twilight / night) and
dew-point class, a month x hour-of-day profile, per-year totals and a few
derived per-city columns (night comfort, dry comfort, humidity). It exists so
the conversational agent can recompute the ranking under a different band,
at night, or with a humidity filter from a few tens of MB instead of the
14 GB cache, and the histogram reproduces `comfort_hours_yr` exactly for any
whole-degree band.

Config: `default.yaml`. Every threshold
that moves the ranking lives there, not in code. `data/` is a gitignored cache;
`cli.py rebuild-utci` re-derives it from the raw fields without refetching.

Sources: GHS-UCDB R2024A V1-2 (JRC); ERA5 / ERA5-HEAT (Copernicus C3S); CAMS
global (Copernicus CAMS); ETOPO 2022 60 arc-second (NOAA NCEI); Natural Earth
10m coastline. UTCI polynomial via `thermofeel` (ECMWF); solar position via
`pvlib`.
