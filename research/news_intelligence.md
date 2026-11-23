# Optional market news research

Inspected/collected 11 November 2026. This is a separate optional input; all core price models function with no news and no paid language-model API.

## Verified sources and restrictions

| Source | Publication timing / verification | Use |
| --- | --- | --- |
| [EIA RSS directory](https://www.eia.gov/tools/rssfeeds/) | Undated live directory, inspected 2026-11-11; directly links the feeds below | Verified discovery, public primary publisher |
| [Today in Energy RSS](https://www.eia.gov/rss/todayinenergy.xml) | Original per-item `pubDate`, including timezone where supplied; captured 2026-11-11 | Downloaded 25 items, 24 with usable original clocks |
| [EIA What's New RSS](https://www.eia.gov/about/new/WNtest3.php) | Original per-item `pubDate`; captured 2026-11-11 | Downloaded 10 items, 10 with usable original clocks |
| [EIA reuse policy](https://www.eia.gov/about/copyrights_reuse.php) | Undated policy inspected 2026-11-11 | Government content may be reused with acknowledgement; third-party exceptions remain applicable. Store publisher feed text and attribution. |
| [OPEC press releases](https://www.opec.org/press-releases.html), [1 November 2026 statement](https://www.opec.org/pr-detail/620-1-november-2026.html) | Article date 2026-11-01; exact original publication clock unverified; inspected 2026-11-11 | Primary research reference only; no historical feature fabricated |
| [OPEC terms](https://www.opec.org/terms-and-conditions.html) | Undated terms inspected 2026-11-11 | Archival/database/redistribution restrictions require care. No bulk OPEC text ingestion into this project. Occasional source-linked research remains separate. |
| MOEW/DGO policy announcements | Dates and original links in `verified_assumptions.md`; original clock/effective-law status often unknown | Manual research evidence; no automatic timestamped news feature until verified |

Actual source URLs, titles, summaries, literal timestamps, UTC conversions, capture times and raw response hashes are stored through `news_items`, `news_sightings` and `captures` in SQLite. The collection has **35 items**, **34 usable original timestamps**, first captured version **2026-11-11T00:16:52.928926+00:00**. Publication range: 2026-09-01T14:00:00Z through 2026-11-10T05:00:00Z. These timestamps are publisher fields, not evidence that this project had those exact text versions at the earlier publication times. One missing clock is quarantined from features.

The 35 stored item versions correspond to **34 distinct article URLs**. Overlapping feeds can describe the same article differently; both raw versions remain available, and features deduplicate by URL using the latest version actually known at origin.

## Classification

Deterministic versioned rules identify possible transmission channels:

| Topic | Economic channel |
| --- | --- |
| OPEC+ production announcements | Crude supply expectations; indirect refined-price effect |
| Refinery operations/disruptions | Gasoline production capacity and product/crude basis |
| Physical supply interruptions/inventories | Regional availability and buffer stocks |
| Shipping, maritime routes and insurance | Freight, delivery delays and landed costs |
| Geopolitical events/sanctions | Supply/demand risk and logistics; direction not assumed |
| Lebanese fiscal/pricing regulation | Taxes, margins, FX treatment and regulated price mapping |

Tags recognize topics, not verified realized disruptions. There is no inferred causal price magnitude, sentiment-to-LBP conversion or LLM numerical forecast. An EIA outlook is commentary/forecast content, not an observed commodity quotation. Rules can miss events, misunderstand negation, or tag a historical discussion. Critical policy interpretation still requires primary-document review; enacted law and a proposal are different.

Coverage is **partial**. The free EIA feeds supply energy context but do not provide comprehensive Lebanese regulation, refinery or geopolitical event monitoring. OPEC original statements remain linked research references. Additional permitted primary feeds may be added only after verifying endpoints, terms and clocks; no paid source access is assumed.

## Availability and optional ablation

A news item enters a feature window only when both its first captured text version and its source publication timestamp are at or before origin, with no timestamp issue. Later edits remain new immutable versions. Feature counts require successful collection spanning the lookback, no gap over two days and a recent successful run; otherwise every channel is **unknown**, not zero. Even a covered feed window is coverage of those feeds, not all world events.

`fuel-forecast news-ablation` compares small ridge models with/without news on exactly the same covered origins, with the same chronological folds and purging. Core market/domestic columns remain identical. The present result has **zero eligible historical paired predictions** because the first captured news version is after every development origin. Incremental predictive skill is unknown, and news is excluded from the saved Part 5 core models. Retroactively downloading a recent summary does not cure this limitation.

No recurring automation is enabled. Repeated authorized collection can build prospective text vintages for later research. RSS publication date alone never establishes the availability of the exact retrieved wording during a historical forecast.
