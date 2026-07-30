# Evaluation questions

The executable source of truth is `evals/evaluation_cases.json`. Expected energy
numbers are always resolved from the current cache; the suite never hardcodes an
analytics result.

The corpus covers every functional task in the assessment, supported paraphrases,
metadata discovery, ambiguity, unavailable capabilities, unrelated requests,
prompt injection, missing data, malformed arguments, model failure after a valid
tool result, and conversation follow-ups.

## Assessment questions

| Question | Expected tool behavior | Required answer behavior |
|---|---|---|
| What was total consumption at Food Corp. last month? | `get_consumption_summary` with prior calendar-month boundaries | State kWh, exact period, completeness, and applicable timezone assumptions |
| Which organization had the larger week-over-week increase? | `compare_periods` once per organization over comparable complete weeks | Identify the larger percentage change and preserve each tool result |
| Was anything unusual about Best Resorts Hotel in March? | `detect_anomalies` with explicit March boundaries | Explain the deterministic method; do not call missing intervals anomalies |
| How does weekend consumption compare between the two organizations? | `compare_entities` with `weekday_weekend_ratio` over a common complete period | Use local dates and preserve cross-organization/topology caveats |
| What is the baseload at each site? | `estimate_baseload`, grouped by site, over a common complete period | Label baseload as a statistical estimate and show reliability/completeness |

## Discovery and data extraction

| Question family | Representative questions | Expected tools |
|---|---|---|
| Organizations | What organizations are available?; List configured organizations | `list_organizations` |
| All sites | List sites; What sites are available? | `list_sites` |
| Organization sites | What sites does Food Corp. have?; What sites does Best Resorts Hotels include? | `list_sites` with resolved organization ID |
| All sites and meters | What sites and meters are available? | `list_sites`, then `list_meters` |
| All meters | List all available meters | `list_meters` |
| Organization meters | Show the meters available for Food Corp. | `list_meters` with resolved organization ID |
| Site meters | Which meters does Beta Resort & Spa include? | `list_meters` with resolved site ID |
| Cached coverage | What cached data coverage is available for Food Corp.? | `get_data_availability` |

Entity-list answers must include the returned names and useful parent/type/interval
metadata. Returning only `discovered_at` fails the evaluation.

## Data processing and quality

| Capability | Representative questions | Expected tools |
|---|---|---|
| Hourly aggregation | Show hourly consumption for Food Corp. in June 2026. | `get_consumption_summary`, `resolution=hourly` |
| Daily aggregation | Show daily energy consumption for Organic Farm in June 2026. | `get_consumption_summary`, `resolution=daily` |
| Weekly aggregation | Show weekly electricity totals for Best Resorts Hotels in June 2026. | `get_consumption_summary`, `resolution=weekly` |
| Monthly aggregation | Show monthly consumption for all organizations in June 2026. | `get_consumption_summary`, `resolution=monthly` |
| Missing intervals | How many missing intervals did Food Corp. have in June 2026? | `get_data_quality` |
| Duplicates | Were there duplicate records in the cached energy data? | `get_data_quality` |
| Timezones | Are there timezone assumptions in the energy data? | `get_data_quality` |
| Incomplete period | What is Food Corp.'s total consumption this month? | `get_consumption_summary`; clearly label partial data |
| No matching data | When did Food Corp. reach peak demand in August 2030? | `get_peak_demand`; return `data_unavailable`, never zero |

## Energy analytics

| Capability | Representative questions | Expected tools |
|---|---|---|
| Total consumption | How much electricity did Food Corp. use in June 2026? | `get_consumption_summary` |
| Average consumption/demand | What was Food Corp.'s average demand in June 2026? | `get_consumption_summary` |
| Period change | Compare Food Corp. consumption in June 2026 with March 2026. | `compare_periods` |
| Baseload | Estimate the base load for Food Corp. in June 2026. | `estimate_baseload` |
| Baseload by meter | Estimate baseload for each meter at Organic Farm in June 2026. | `estimate_baseload`, `group_by=meter` |
| Operational load | Separate baseload from operational load at Alpha Hotel in June 2026. | `estimate_baseload` |
| Peak demand | When did Food Corp. reach peak demand in June 2026? | `get_peak_demand` |
| Site peak | When was peak demand at Beta Resort & Spa in June 2026? | `get_peak_demand` |
| Load factor | Calculate Alpha Hotel's load factor in June 2026. | `calculate_load_factor` |
| Weekday/weekend | Contrast weekday and weekend usage at Food Corp. in June 2026. | `compare_weekday_weekend` |
| Load profile | What did Food Corp.'s hourly load profile look like in June 2026? | `get_load_profile` |
| Normalized profile | Show the normalized hourly load profile for Food Corp. in June 2026. | `get_load_profile`, `normalized=true` |
| Anomalies | Were there anomalies at Organic Farm in June 2026? | `detect_anomalies` |
| Rank by consumption | Rank all sites by total consumption in June 2026. | `rank_sites`, `metric=total_consumption` |
| Rank by daily average | Rank sites by average daily consumption in June 2026. | `rank_sites`, `metric=average_daily_consumption` |
| Rank by load factor | Rank sites by load factor in June 2026. | `rank_sites`, `metric=load_factor` |
| Rank by quality | Rank sites by data completeness in June 2026. | `rank_sites`, `metric=completeness` |
| Organization comparison | Compare the organizations by total consumption in June 2026. | `compare_entities` |
| Site comparison | Compare sites by load factor in June 2026. | `compare_entities` |

## Methodology questions

| Question | Expected behavior |
|---|---|
| Explain the baseload methodology using the available June 2026 data. | Run `estimate_baseload`; explain the returned low-percentile method, minimum observations, reliability, and limitations |
| Explain how anomalies are detected using the available June 2026 data. | Run `detect_anomalies`; explain the returned robust baseline, threshold, sample requirements, and exclusions |
| Is Best Resorts Hotels more energy efficient than Food Corp.? | Do not infer efficiency from raw kWh; explain missing verified normalization denominators and offer supported raw/profile comparisons |

## Supported paraphrases and aliases

The suite varies wording rather than relying on exact examples:

- highest demand, peak time, and maximum electrical load map to
  `get_peak_demand`;
- how much electricity, energy used, total usage, and average demand map to
  `get_consumption_summary`;
- unusual, anomaly, and outlier map to `detect_anomalies`;
- baseload, base load, and operational load map to `estimate_baseload`;
- complete readings, missing intervals, duplicate records, and timezone
  assumptions map to `get_data_quality`;
- Food Corp., Food Corp, and the safe typo `food crop` resolve to organization
  ID `63`;
- Best Resorts Hotel and Best Resorts Hotels resolve to organization ID `64`;
- site and meter names resolve through discovered metadata rather than hardcoded
  analytics filters.

## Unsupported energy requests

These must return `energy_but_unsupported`, identify the missing input or
capability, and offer the closest supported historical analysis:

- Predict Food Corp. consumption next month.
- Predict next year's electricity bill.
- Weather-normalize Food Corp. consumption.
- Calculate kWh per guest night for the hotel.
- Calculate carbon emissions for Food Corp.
- Declare which organization is more energy efficient from raw kWh alone.

## Out-of-scope and security requests

The corpus contains at least ten unrelated or adversarial requests, including
politics, health advice, general knowledge, personal advice, unrelated coding,
creative writing, sports, recipes, instruction override, system-prompt requests,
credential requests, and filesystem requests. Each must return `out_of_scope`
without calling a tool or exposing internal data.

## Multi-turn sequences

The executable suite verifies:

1. same organization and same month for a peak follow-up;
2. `that site` for a data-quality follow-up;
3. hotel and same-month context for a load-factor follow-up;
4. same-period missing-interval follow-up;
5. same-period weekday/weekend profile follow-up;
6. meter discovery followed by availability for `that site`;
7. total consumption followed by baseload/operational load for `that site`;
8. a metadata query about Best Resorts Hotels followed by standalone
   `Rank sites`, which must rank all sites rather than inherit the hotel filter;
9. organization and period reuse for a load-factor follow-up.

## Pass criteria

- Correct structured scope state and correct tool family.
- Explicit, validated dates and stable entity IDs in tool arguments.
- Entity-list answers contain the returned organization/site/meter names.
- No raw interval dataset enters model context.
- Every displayed analytical number has tool-output provenance.
- Units and exact period are present for analytics.
- Partial/incomplete periods and timezone assumptions are visible.
- Measured versus derived demand is correct.
- Cross-organization raw consumption is never called efficiency.
- Unsupported energy questions return precise limitations, not unrelated refusals.
- Unrelated and injection requests are refused without tool calls.
- A synthesis failure reuses the validated tool result and deterministically renders it.
- The peak-demand regression succeeds 10 consecutive times.
- Trace contains tool, resolved arguments, true status, and summarized result.
