# Delivery ALNS

This project solves a multi-day delivery scheduling problem with one courier and one vehicle. Each day the courier starts at the depot, visits selected customers, and returns to the depot. Each customer has one order that should be delivered exactly once during the week, and each customer can have multiple valid receiving time windows across different days.

## Why This Is Multi-Period VRPTW With Multiple Time Windows

The problem combines routing, scheduling, and day assignment:

- Routing: choose the customer order inside each daily route.
- Scheduling: choose arrival and service times that respect time windows.
- Multi-period assignment: choose which day a customer is delivered.
- Multiple time windows: a customer may have several receiving windows on the same or different days.

The code computes Euclidean distance from kilometer coordinates and converts it to travel time using the 50 km/h speed limit:

```text
travel_time = distance / 50 * 60 = distance * 1.2 minutes
```

## Why ALNS

Greedy methods can get stuck because early local choices consume scarce time-window capacity. Adaptive Large Neighborhood Search (ALNS) repeatedly removes part of the weekly schedule and repairs it. Multiple destroy and repair operators are selected adaptively based on historical performance.

## Improved Opportunity Cost Logic

Opportunity Cost is split into two parts so the algorithm does not accidentally improve distance by pushing orders to later days:

```text
feasibility_OC(i,d) = best_future_insertion_cost - best_today_insertion_cost
lateness_OC(i,d) = delivery_day - first_available_day
```

If no future feasible insertion exists, the future cost is a large penalty. This helps prioritize customers that may become impossible later. Lateness is handled separately, because assigning an order later than its first available day directly increases the objective.

The OC repair operator uses:

```text
adjusted_cost =
    insertion_cost
  - eta_oc * feasibility_OC
  + theta_postponement * postponement_increment
  + phi_delivery_day * delivery_day_increment
```

Default parameters:

```text
eta_oc = 0.5
theta_postponement = 1000
phi_delivery_day = 500
```

ALNS-OC also includes `early_day_repair` and `relocate_to_earlier_day`, which explicitly try to place or move customers to earlier feasible days when the full objective improves.

## How To Run

Install dependencies:

```bash
pip install -r requirements.txt
```

Run the full workflow:

```bash
python main.py --data Data_B.zip --out outputs --seed 42 --iterations 5000
```

Run a quicker debug workflow:

```bash
python main.py --data Data_B.zip --out outputs --seed 42 --iterations 300 --debug
```

The `--data` argument can be either a zip file or a folder containing `locations.csv` and `time_windows.csv`.

## Methods

- Nearest Neighbor: repeatedly appends the nearest feasible customer.
- Earliest Deadline First: repeatedly appends the feasible customer with earliest closing time.
- Greedy Insertion: inserts the cheapest feasible customer-position pair.
- ALNS-Base: random, worst, and related removal with cheapest and regret-2 repair.
- ALNS-OC: full ALNS with opportunity-cost removal/insertion, early-day repair, time-window conflict removal, regret-3, slack-aware insertion, and earlier-day relocation local search.

## Objective Function

The objective uses large penalties:

```text
F = 1,000,000 * undelivered
  + 10,000 * postponement
  + 10 * distance
  + 1 * waiting
  + 1 * low_slack_penalty
```

This makes completion dominate distance, which matches the competition goal: deliver as many orders as possible first, then reduce postponement, distance, waiting, and schedule risk.

## Output Files

- `outputs/metrics/results_comparison.csv`: method-level metrics for direct report tables.
- `outputs/schedules/best_schedule.csv`: visit-level schedule for the best objective method.
- `outputs/schedules/schedule_nearest_neighbor.csv`: detailed schedule for Nearest Neighbor.
- `outputs/schedules/schedule_edf.csv`: detailed schedule for Earliest Deadline First.
- `outputs/schedules/schedule_greedy.csv`: detailed schedule for Greedy Insertion.
- `outputs/schedules/schedule_alns_base.csv`: detailed schedule for ALNS-Base.
- `outputs/schedules/schedule_alns_oc.csv`: detailed schedule for ALNS-OC.
- `outputs/schedules/undelivered_orders.csv`: customers not delivered by the best method.
- `outputs/metrics/daily_route_summary.csv`: daily route totals, including return-to-depot distance.
- `outputs/metrics/operator_history.csv`: adaptive ALNS operator weights and usage.
- `outputs/metrics/iteration_history.csv`: objective and acceptance trace for ALNS-OC.
- `outputs/logs/alns_run.log`: preprocessing, baseline, and ALNS progress logs.
- Optional plots: `objective_progress.png` and `method_comparison.png`.

## Interpreting `results_comparison.csv`

Compare methods first by `delivered_orders` and `completion_rate`, then by `objective`. If two methods deliver the same number of orders, use `postponement_penalty`, `total_distance`, `total_waiting_time`, and `min_slack` to explain operational quality. Total distance includes the return from the last customer back to the depot; this return leg appears as a depot row in each schedule file and as `return_to_depot_distance` in `daily_route_summary.csv`.

For the report, a strong result is usually:

1. ALNS methods deliver at least as many orders as baselines.
2. ALNS-OC improves or matches ALNS-Base on objective.
3. ALNS-OC has lower postponement or safer slack when completion is tied.

## Parameter Tuning / Grid Search

ALNS-OC has several parameters that control the balance between routing cost, postponement risk, operator learning, and simulated annealing exploration. Tuning is needed because one debug run is not enough: ALNS contains random destroy/repair choices, so a single seed can make one configuration look better or worse by chance.

The recommended tuning workflow is not a full factorial grid. The full parameter space creates more than 200,000 configurations before multiplying by seeds, which is not practical and not necessary. Use a four-stage process:

1. Screening: small/debug runs only to verify the pipeline.
2. Random search: sample broad regions of the full parameter space.
3. Focused tuning: zoom into the best region using a smaller custom grid.
4. Validation and final comparison: evaluate the selected config on unseen seeds and compare all methods fairly.

Random search is usually a better use of runtime here: it samples across the whole space and can find strong regions without evaluating every combination.

- Raw results keep every config/seed run, including failures. This is useful for traceability and resume mode.
- Summary results aggregate by `config_id`, which is better for deciding which configuration is robust.

Tuned parameters:

- `eta_oc`: strength of feasibility opportunity cost. Higher values prioritize orders that may lose future feasible insertion options.
- `theta_postponement`: penalty for increasing postponement. This prevents OC from pushing orders to later days.
- `phi_delivery_day`: penalty for later delivery days, encouraging earlier feasible assignment.
- `rho_operator_learning`: adaptive operator weight learning rate.
- `temperature_initial`: starting temperature for simulated annealing.
- `cooling_rate`: temperature decay rate.
- `removal_fraction_min` / `removal_fraction_max`: destroy neighborhood size.
- `use_slack_penalty`: whether to penalize low slack.
- `use_early_day_repair`: whether to include the repair operator that prefers earlier feasible days.
- `use_relocate_to_earlier_day`: whether local search tries to move delivered orders earlier.

Ranking in `tuning_results_summary.csv` does not use objective alone. Completion rate is ranked first, because a low objective is misleading if a method leaves many orders undelivered. Then the ranking considers undelivered orders, objective, postponement, distance, and runtime.

### Stage 1: Quick Debug

This only checks that tuning code, resume mode, and CSV exports work. Do not use this to make conclusions.

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode quick --iterations 100 --tune-seeds 1 --max-configs 5 --debug --resume
```

### Successive Halving Presets

The project supports `--tuning-stage` presets. This is the recommended way to avoid running broad and deep tuning at the same time.

Screening:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode full --search-strategy random --n-configs 20 --iterations 200 --tune-seeds 1 --tuning-stage screening --tune-light --resume
```

Focused:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode full --search-strategy random --n-configs 10 --iterations 800 --tune-seeds 1,2,3 --tuning-stage focused --resume
```

Validation:

```bash
python main.py --data ..\Data_B --out outputs --use-best-config outputs\tuning\best_config.json --iterations 3000 --seeds 1,2,3,4,5
```

During tuning, early stopping is enabled by default:

```text
patience = 150
min_improvement = 1000
```

If the best objective does not improve enough during the patience window, the current run stops early and is recorded as `early_stopped`. Poor configs can also be marked `pruned` after enough iterations. Checkpoints are written every 50 iterations to:

```text
outputs/tuning/tuning_checkpoints.csv
```

This file is useful when a long tuning process is interrupted manually: the current run may not have reached `tuning_results_raw.csv`, but its intermediate best metrics are still visible.

`--tune-light` is intended for screening only. It reduces expensive repair/local-search behavior while keeping feasibility exact. Final validation should run without light mode.

### Stage 2: Screening Search

Use random search to sample the full space without enumerating all combinations.

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode full --search-strategy random --n-configs 50 --iterations 1500 --tune-seeds 1,2,3 --resume
```

For a lighter first pass:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode full --search-strategy random --n-configs 10 --iterations 300 --tune-seeds 1 --resume --debug
```

### Stage 3: Focused Tuning

After screening, inspect `outputs/tuning/top_10_configs.csv`. If the best configs concentrate around a region, use the provided focused grid:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode custom --grid-file config_grid_focused.json --iterations 2000 --tune-seeds 1,2,3 --resume
```

### Stage 4: Validation And Final Comparison

Validate the selected config on seeds that were not used during tuning:

```bash
python main.py --data ..\Data_B --out outputs --use-best-config outputs\tuning\best_config.json --iterations 5000 --seeds 4,5,42
```

Then run the final fair comparison using the same iteration budget for ALNS-Base, ALNS-OC default, and ALNS-OC tuned:

```bash
python main.py --data ..\Data_B --out outputs --use-best-config outputs\tuning\best_config.json --iterations 5000 --seeds 1,2,3,4,5
```

### One-Command Pipeline

To run the staged workflow in order, use the PowerShell pipeline:

```powershell
.\scripts\run_tuning_pipeline.ps1
```

or the Windows wrapper:

```cmd
scripts\run_tuning_pipeline.cmd
```

The default pipeline runs:

1. quick debug tuning,
2. screening random search,
3. focused tuning,
4. validation on unseen seeds,
5. final fair comparison.

For a lighter run:

```powershell
.\scripts\run_tuning_pipeline.ps1 -ScreeningConfigs 10 -ScreeningIterations 200 -FocusedConfigs 5 -FocusedIterations 500 -ValidationIterations 1000 -FinalIterations 1000
```

To resume from focused tuning after screening already completed:

```powershell
.\scripts\run_tuning_pipeline.ps1 -SkipQuick -SkipScreening
```

Custom tuning grid:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode custom --grid-file config_grid.json
```

Resume mode:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode quick --iterations 1000 --tune-seeds 1,2,3 --resume
```

Resume mode skips `config_id + seed` pairs already marked `success` in `outputs/tuning/tuning_results_raw.csv`. This matters for long experiments where the run may be interrupted.

`--n-configs` is preferred for large tuning because it samples configurations across the whole parameter space. `--max-configs` is still available for debugging, but it simply takes the first N configurations from the generated list.

Full mode defaults to random search if `--search-strategy` is omitted. You can still force full factorial grid search with `--search-strategy grid`, but that is usually too large for final experiments.

Latin sampling is also available:

```bash
python main.py --data ..\Data_B --out outputs --tune --tune-mode full --search-strategy latin --n-configs 50 --iterations 1500 --tune-seeds 1,2,3 --resume
```

Tuning outputs:

- `outputs/tuning/tuning_results_raw.csv`
- `outputs/tuning/tuning_results_summary.csv`
- `outputs/tuning/best_config.json`
- `outputs/tuning/top_10_configs.csv`
- Optional plots in `outputs/tuning/`

Final tuned run:

```bash
python main.py --data ..\Data_B --out outputs --use-best-config outputs/tuning/best_config.json --iterations 10000 --seeds 1,2,3,4,5
```

This creates:

- `outputs/metrics/final_tuned_repeated_runs.csv`
- `outputs/metrics/final_method_comparison.csv`
- `outputs/metrics/final_method_comparison_summary.csv`

In the final paper, report the tuned configuration from `best_config.json`, the ranking row from `tuning_results_summary.csv`, and the final repeated-run comparison against Nearest Neighbor, Earliest Deadline First, Greedy Insertion, ALNS-Base, ALNS-OC default, and ALNS-OC tuned.
