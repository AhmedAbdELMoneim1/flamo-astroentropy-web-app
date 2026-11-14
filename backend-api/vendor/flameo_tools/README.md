# flameo_tools

Standalone query tools over `serving.db` for the Flame in Freefall voice agent and dashboard. Python standard library only (`sqlite3`, FTS5); nothing is imported from the pipeline package; no LLM / API call. Every tool returns a fixed JSON shape (version 1).

## 1. Import and call
```python
import flameo_tools as F

F.configure("local_data/serving.db")              # or set the environment variable FLAMEO_DB
answer = F.call("scenario_coverage", scenario="Moon")     # a dict (JSON-serialisable)
specs  = F.tool_specs()                           # name + docstring + JSON schema for each tool (function calling)
F.REGISTRY["rank_agents"].fn(fuel_class="liquid") # or call the function directly
```
`serving.db` is opened read-only (`mode=ro`, `check_same_thread=False`), one cached connection per path. A sqlite3 connection must not run two statements at once, so the tools are NOT safe for simultaneous calls from several threads: callers must serialize them (the voice agent wraps every call in a lock). A call takes a few milliseconds to a few tenths of a second.

## 2. Return shapes
**Answer** (every tool except `show_view` / `get_dashboard`):
```json
{"version": 1, "tool": "scenario_coverage", "question": "scenario_coverage(Moon)",
 "speak": ["spoken sentences ..."],            // the ONLY facts / numbers the voice may say
 "kpis":  [{"id", "label", "value", "unit", "basis": "X of Y tests", "trust"}],
 "charts":[{"id", "type": "bar|line|scatter", "title", "x": {"label","unit"}, "y": {"label","unit"}, "series": [{"name", "points": [{"x","y"}]}]}],
 "table": {"columns": [{"key","label","unit?"}], "rows": [{}]},      // or null
 "gaps":  ["what is not known ..."],
 "source": {"label": "...", "mock": false, "refs": ["PSI-20", "F-P2-..."]},
 "facts": [{"value": 49}, {"text": "..."}]}      // every number / free text that speak[] uses
```
**Dashboard** (`show_view`, `get_dashboard`): `{version, view, scenario, coverage, headline, key_points[], kpis[] (max 4), charts[] (max 2), table (max 20 rows, every row carries the view's key value), gaps[], speak[], source, facts}`.
Additive keys the frontend may ignore: `ranking`, `pillar`, `for_scenario` (rank_investigations), `facts`, `cards[]` (the authors' findings with `wording`, `evidence_basis`, `quote`, `paper`, `page`), `nearest {scenario, metric, n}`, `closest_tested` and `level_oxygen_rich_flames` (spacesuit answers only), `level`, `level_n2_stated`, `ranked`, `objectives`, `table_key`. `shapes.validate(answer, "answer" | "dashboard")` returns a list of problems (empty = valid) and checks that every number in `speak` is also in `facts` / kpis / table / charts.

## 3. The tools (route each question to one; 9 intent tools + `show_view`)
| tool | arguments | answers | example question |
|---|---|---|---|
| `get_investigation` | `psi` (id, number or name: PSI-20, 20, BRE, BASS-II) | what the investigation is, tests, condition ranges (ambient oxygen apart from burner-stream oxygen), fuels, materials, outcomes recorded | "What is BRE?" |
| `compare` | `psi_a`, `psi_b` | side-by-side table, what overlaps and what is missing; no ranking | "Compare BASS and BASS-II" |
| `rank_materials` | `metric="spread rate"`, `scenario=None` | spread rate by investigation x material x flow direction; ranks only inside one comparable group of one PSI; limit findings as the authors' words | "Which material spreads fastest?" |
| `scenario_coverage` | `scenario` (iss, moon_base, exploration_10_2, exploration_8_2, spacesuit, high_o2; aliases Moon, ISS ...) | tests near the atmosphere; how many state nitrogen or air; level and `level_n2_stated` | "Tests near the Moon base atmosphere?" |
| `get_findings` | `x`, `y`, `fuel=None` (field names or words: oxygen, spread rate ...) | paper findings worded by evidence basis + supporting test points | "How does spread rate change with oxygen?" |
| `rank_agents` | `fuel_class=None` | diluent (CO2, He; nitrogen as balance gas) per investigation: tests above zero, ranges, sources, the authors' effects | "Which suppressant works best?" |
| `gaps` | `scenario=None` | what is not known; Mars / partial gravity = no PSI data; no scenario = incomplete PSI x field cells | "What don't we know for Mars?" |
| `search_text` | `query`, `psi=None` | cards and passages (full sentences, document title, page) | "Why are space smoke particles bigger?" |
| `oxygen_effect` | `scenario=None`, `material=None` | the oxygen of the scenario atmosphere, the accepted FLIGHT findings that relate oxygen to flame behaviour (config list, each with its evidence wording), the BRE thesis sentence on 26 % and steady flames, the cool-flame limit, and the oxygen-pressure chart. Always carries the gap line "The PSI data does not set a single safe or dangerous oxygen level; these are the conditions where the tests still burned." Never a threshold, never "safest" | "What oxygen level makes the spacecraft dangerous?" |
| `rank_investigations` | `pillar=None` (prevention, flammability, detection, suppression), `scenario=None` | the investigations most relevant to a question: lexicographic by registry tier (A, B, C, M), flight before ground, tests near the scenario (or in the data), accepted paper findings (flight first). `ranking[]` rows `{rank, psi, name, tier, pillars, tests, tests_label, findings}`; bar value = `tests`, a real count, no score. Never rates safety; spacesuit counts only burner-stream tests, never "coverage" | "Which experiments matter most for the Moon base?" |
| `show_view` | `view` (ignition, materials, flame_spread, smoke, suppression, gaps), `scenario=None`, `params=None` | Dashboard JSON | "Show me the flame spread view" |
| `get_dashboard`, `query_data` | `(view, scenario, inputs)`, `(metric, filters)` | mock-compatible wrappers; `query_data` metrics: ignition_time_by_material, material_ranking, spread_vs_oxygen, smoke_particle_size, extinguisher_amount (not supported by the data: says so) | |

`router_examples.yaml` lists example questions with tool and arguments for the router prompt; every docstring says what the tool answers, its arguments and what it never does.

## 4. Rules the tools keep (do not work around them in the agent)
- Say only what is in `speak[]`. Numbers, units and names there are already spoken-form (no field names, no formulas).
- Never merge trust levels: every KPI has `basis` ("X of Y tests") and `trust` (table, document, assumed, paper). An assumed pressure is "assumed ISS cabin ambient"; a stated range is spoken as "about 99 kilopascals (99.2 to 99.5)".
- "On the ISS" only for flight evidence; other cards use their own phrase (normal-gravity test, drop tower, model, theory, earlier flight, experiment type not stated).
- Atmosphere scenarios count ambient oxygen only; burner-stream oxygen of inverse flames is separate and labelled; He / CO2 diluent tests are not counted. Every coverage answer says how many near tests state nitrogen or air (per test or once for the whole PSI) and how many do not state the diluent gas.
- Rankings only inside a comparable group of one PSI; never "safer", never a mean across varied conditions.
- Mars: no value, ever. Zero counts are not spoken as numbers; a "No ..." sentence and the nearest scenario with data are.

## 5. Rebuild (minutes, no API)
```bash
.venv/bin/python -m psi_pipeline.serving build --out local_data/serving.db --verify   # --verify builds twice and compares the canonical dump hash
```
Inputs (read-only): `local_data/pipeline.db`, `reports/stage4_field_values_final.csv`, `reports/stage5/paper_field_values.csv`, `reports/stage5/findings_all.csv`, `config/serving.yaml`, `config/psi_registry.yaml`, `config/chat_extractions.yaml`. Rerun order when the pipeline is rebuilt: Stage 4 lane A -> Stage 4 `apply()` -> `python -m psi_pipeline.extract.bre_tables --apply` -> Stage 5 -> `tools/requote_soot.py` -> the Stage 6 build. `meta` holds schema_version, input hashes, the config copy and the dump hash.

## 6. Change a use case
- **Scenario** (point, region, tolerance, aliases, nearest-covered order): edit `scenarios`, `coverage`, `nearest_covered` in `config/serving.yaml`, rebuild.
- **View** (KPIs, charts, table fields and key): edit `views` in `config/serving.yaml` (a KPI is `kind: tests_with | range | psis_with | distinct_values`, a `field`, a `noun` for the spoken sentence, optional `positive: true`); rebuild, no code.
- **Spoken labels, fuel names, wording per evidence basis, comparable-group tolerances, agent fields**: the same file (`labels`, `fuel_names`, `wording`, `groups`, `agents`).
- **New tool**: write one function in `tools.py` (docstring for the router, returns `_ans(...)`), add one `Tool(...)` line in `registry.py`, add router examples to `router_examples.yaml` and at least two goldens to `tests/golden/golden_questions.yaml`. Nothing else changes; `serving.db` is untouched.
- **Stage 7 example (rank_investigations)**: the tier already lives in `config/psi_registry.yaml` (copied to `psi.tier`); the tool is one function in `tools.py` + one `Tool(...)` line + three router examples + goldens g30-g40, and `python -m psi_pipeline.serving build --verify` (only the config copy in `meta` changes). `partial_gravity_text` and the first line of `rank_agents` are config / wording changes with their goldens (g13, g14, g15).
- **A use case that needs data never extracted** (a new field from documents or papers) is a Stage 4 / 5 style extraction, not a Stage 6 change.

## 7. Tests
`pytest tests/test_serving.py tests/test_tools.py tests/test_golden_checks.py`: builder checks, a tiny synthetic db for the tools, 40 golden questions (g01-g40) with must-contain facts, and the shared negative checks (no spoken zero counts, no "1 PSIs", no ellipsis or repeated opening, every view-table row has the key value, "tests with X" counts only X > 0, every "nearest" pointer has data).
