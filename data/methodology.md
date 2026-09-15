# Global city outdoor-comfort ranking

How many daylight hours a year is it thermally comfortable to be outdoors,
walking around or going for a casual run?

Generated 2026-09-15 from 1118 scored cities
(1114 eligible for the ranking, subset `all`), UTCI over
2010-2024.

**Read the sensitivity section before quoting a rank.** Several of the choices
below move cities by tens of places, and the ranking is only meaningful
alongside the assumptions that produced it.

## Method

1. **Cities** — JRC GHS-UCDB R2024A urban centres, population >= 500,000.
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
| Liverpool | 2,301 | 1,685 | -27% |
| Leeds | 2,250 | 1,713 | -24% |
| Dublin | 2,548 | 1,956 | -23% |

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
| – | Santa Cruz de Tenerife | Spain | 4,434 | 4,315 | 4,280 | 0.93 | 285 | 3 | 0.87 | 8.5 | 1.00 | 3,836 | <500k ref coast+rel |
| – | Las Palmas de Gran Canaria | Spain | 4,338 | 4,043 | 4,297 | 0.91 | 283 | 2 | 0.88 | 9.4 | 1.00 | 3,810 | <500k ref coast+rel |
| 1 | Lima | Peru | 4,360 | 3,568 | 4,496 | 0.94 | 278 | 0 | 0.89 | 13.0 | 0.93 | 3,642 | coast+rel |
| 2 | Sana'a | Yemen | 4,087 | 2,957 | 4,350 | 0.86 | 309 | 1 | 0.95 | 13.2 | 0.93 | 3,623 | relief |
| 3 | Honolulu | United States | 4,124 | 3,278 | 4,434 | 0.88 | 296 | 2 | 0.88 | 7.6 | 1.00 | 3,611 | coast+rel |
| 4 | Nakuru | Kenya | 3,979 | 2,896 | 4,213 | 0.84 | 296 | 1 | 0.94 | 11.8 | 0.96 | 3,596 | relief |
| 5 | Aguascalientes | México | 3,819 | 2,927 | 4,182 | 0.81 | 275 | 1 | 0.93 | 7.1 | 1.00 | 3,547 | relief |
| 6 | San Luis Potosí | México | 3,798 | 3,103 | 4,006 | 0.81 | 288 | 2 | 0.93 | 6.6 | 1.00 | 3,541 | relief |
| 7 | Durango | México | 3,805 | 3,052 | 3,976 | 0.80 | 276 | 2 | 0.93 | 5.4 | 1.00 | 3,528 | relief |
| 8 | Tijuana | México | 4,413 | 4,122 | 4,368 | 0.93 | 282 | 4 | 0.84 | 12.5 | 0.94 | 3,495 | coast+rel |
| – | Funchal | Portugal | 4,070 | 3,547 | 4,138 | 0.86 | 272 | 2 | 0.84 | 8.9 | 1.00 | 3,430 | <500k ref coast+rel |
| 9 | Kenitra | Morocco | 3,963 | 3,366 | 4,212 | 0.83 | 273 | 2 | 0.87 | 10.1 | 1.00 | 3,424 | coast |
| 10 | Querétaro | México | 3,615 | 2,777 | 4,036 | 0.77 | 258 | 2 | 0.92 | 8.6 | 1.00 | 3,308 | relief |
| 11 | Valparaíso | Chile | 4,268 | 4,284 | 3,954 | 0.90 | 243 | 2 | 0.80 | 11.4 | 0.97 | 3,297 | coast+rel |
| 12 | Hargeisa | Somalia | 3,755 | 2,934 | 4,287 | 0.80 | 252 | 1 | 0.88 | 8.6 | 1.00 | 3,286 |  |
| 13 | Polokwane | South Africa | 3,571 | 2,891 | 3,954 | 0.76 | 248 | 1 | 0.91 | 8.2 | 1.00 | 3,259 |  |
| 14 | Cochabamba | Bolivia | 3,724 | 2,819 | 3,852 | 0.79 | 216 | 1 | 0.87 | 5.9 | 1.00 | 3,248 | relief |
| 15 | Puebla | México | 3,798 | 2,995 | 3,921 | 0.82 | 269 | 1 | 0.93 | 13.6 | 0.92 | 3,247 | relief |
| 16 | Morelia | México | 3,585 | 2,613 | 4,029 | 0.76 | 265 | 1 | 0.91 | 10.5 | 0.99 | 3,245 | relief |
| 17 | Saltillo | México | 3,500 | 2,640 | 3,948 | 0.74 | 263 | 2 | 0.92 | 9.6 | 1.00 | 3,223 | relief |
| 18 | Perth | Australia | 3,772 | 3,459 | 3,822 | 0.80 | 239 | 2 | 0.85 | 6.2 | 1.00 | 3,214 | coast |
| 19 | Oaxaca de Juárez | México | 3,465 | 2,447 | 3,995 | 0.75 | 250 | 2 | 0.91 | 7.6 | 1.00 | 3,144 | relief |
| 20 | Rabat | Morocco | 3,926 | 3,275 | 4,233 | 0.82 | 284 | 2 | 0.87 | 13.8 | 0.92 | 3,128 | coast |
| 21 | San Francisco | United States | 4,040 | 3,511 | 4,141 | 0.84 | 242 | 3 | 0.81 | 12.2 | 0.95 | 3,121 | coast+rel |
| 22 | Antananarivo | Madagascar | 3,607 | 3,034 | 3,828 | 0.77 | 229 | 2 | 0.86 | 10.1 | 1.00 | 3,109 |  |
| 23 | Cordoba | Argentina | 3,468 | 3,011 | 3,668 | 0.73 | 237 | 2 | 0.90 | 4.9 | 1.00 | 3,107 |  |
| 24 | Gqeberha | South Africa | 3,927 | 3,786 | 3,790 | 0.83 | 241 | 4 | 0.82 | 11.6 | 0.96 | 3,106 | coast |
| 25 | Tangier | Morocco | 3,732 | 3,295 | 3,882 | 0.78 | 234 | 3 | 0.83 | 9.4 | 1.00 | 3,103 | coast |
| 26 | Sydney | Australia | 3,581 | 3,159 | 3,744 | 0.75 | 245 | 4 | 0.89 | 11.4 | 0.97 | 3,086 | coast |
| 27 | Nairobi | Kenya | 3,948 | 3,348 | 4,058 | 0.83 | 260 | 1 | 0.90 | 16.5 | 0.85 | 3,044 | relief |
| 71 | Valencia | Spain | 3,429 | 2,994 | 3,718 | 0.71 | 178 | 4 | 0.76 | 8.7 | 1.00 | 2,596 | ref coast |

## Sensitivity

Kendall's tau against the baseline ranking. Low tau means the variant asks a
materially different question; a city whose rank survives every variant is a
real result, and one that moves is an artefact of the thresholds.

| Variant | Kendall tau | Mean rank change | Max rank change |
|---|---:|---:|---:|
| `metric_raw_hours` | 0.561 | 181.6 | 594 |
| `metric_fraction` | 0.572 | 176.2 | 594 |
| `metric_worst_month` | 0.632 | 145.0 | 547 |
| `profile_running` | 0.649 | 142.1 | 700 |
| `aq_penalty_off` | 0.756 | 103.4 | 412 |
| `evenness_shannon` | 0.761 | 94.4 | 680 |
| `band_warm_+2C` | 0.796 | 83.2 | 329 |
| `exposure_0` | 0.797 | 84.7 | 363 |
| `band_cool_-2C` | 0.801 | 81.7 | 393 |
| `exposure_1` | 0.829 | 70.8 | 368 |
| `profile_sitting` | 0.893 | 45.3 | 368 |
| `rain_penalty_off` | 0.894 | 43.2 | 528 |
| `exposure_0.25` | 0.899 | 42.4 | 195 |
| `exposure_0.75` | 0.907 | 38.4 | 202 |
| `daylight_sunrise_0deg` | 0.935 | 27.1 | 257 |
| `elevation_correction_off` | 0.971 | 11.0 | 269 |
| `baseline` | 1.000 | 0.0 | 0 |

Least stable cities — their position is a statement about the parameters, not
about the climate:

| City | Rank volatility (sd) | Median rank |
|---|---:|---:|
| Oslo | 261.5 | 890 |
| Stockholm | 244.9 | 1070 |
| Gothenburg | 235.1 | 934 |
| Copenhagen | 226.4 | 977 |
| Ambon | 225.5 | 448 |
| Newcastle upon Tyne | 222.0 | 775 |
| Denpasar | 220.7 | 471 |
| Calgary | 218.8 | 660 |

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
  is the city's surroundings, not the city. 578 of 1118 scored
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
