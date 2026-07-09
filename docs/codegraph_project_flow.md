# Codegraph Project Flow

This document redraws the main code paths of the `delivery_alns` project. It is based on the local `.codegraph/codegraph.db` index plus the current Python module/import structure.

## 1. Top-Level Runtime Flow

```mermaid
flowchart TD
    CLI["main.py\nparse_args()"] --> CTX["build_context()\nlocations, windows, matrices, indexes"]
    CTX --> MODE{"Run mode"}

    MODE -->|"default"| EXP["experiments.run_all_experiments()"]
    MODE -->|"--tune"| TUNE["tuning.run_grid_search()"]
    MODE -->|"--use-best-config"| FINAL["main._run_final_tuned_comparison()"]

    EXP --> BASE["baselines.run_baselines()"]
    EXP --> INIT["initial_solution.regret_insertion_initial_solution()"]
    EXP --> ALNSB["alns.run_alns(... variant='base')"]
    EXP --> ALNSOC["alns.run_alns(... variant='oc')"]
    EXP --> REPORT["reporting exports\nresults, schedules, summaries"]

    TUNE --> GRID["parameter_grid.get_parameter_grid()"]
    TUNE --> INITCACHE["cached initial solution per seed"]
    TUNE --> ALNSTUNE["alns.run_alns(... variant='oc')"]
    TUNE --> RAW["tuning_results_raw.csv"]
    TUNE --> CKPT["tuning_checkpoints.csv"]
    TUNE --> TSUM["tuning_report.aggregate_tuning_results()"]
    TSUM --> BEST["best_config.json"]

    FINAL --> BASE2["baselines"]
    FINAL --> INIT2["initial solution"]
    FINAL --> ALNSB2["ALNS-Base"]
    FINAL --> ALNSD["ALNS-OC default"]
    FINAL --> ALNST["ALNS-OC tuned"]
    FINAL --> FOUT["final_method_comparison*.csv"]
```

## 2. Data And Feasibility Spine

```mermaid
flowchart LR
    DATA["Data_B.zip / Data_B folder"] --> DL["data_loader.load_data()"]
    DL --> LOC["locations_df"]
    DL --> TW["time_windows_df"]
    LOC --> DIST["distance.build_matrices()"]
    TW --> TWI["feasibility.build_time_window_index()"]

    DIST --> CTX["context\ntravel_time, distance, id_to_idx"]
    TWI --> CTX
    LOC --> CTX

    CTX --> ER["feasibility.evaluate_route()"]
    ER --> VISIT["models.Visit records"]
    ER --> ROUTE["models.Route\nfeasible, distance, waiting, slack"]

    ROUTE --> SOL["models.Solution"]
    SOL --> OBJ["objective.evaluate_solution()"]
    OBJ --> METRICS["objective + metrics"]
```

Key point: every constructive, repair, local-search, and ALNS move eventually goes through `evaluate_route()`, so multiple time windows and return-to-depot accounting stay centralized.

## 3. ALNS-OC Loop

```mermaid
flowchart TD
    START["Initial Solution"] --> CURRENT["current solution"]
    CURRENT --> SELECTD["roulette destroy operator"]
    SELECTD --> DESTROY["destroy_operators\nrandom / worst / related /\ntime-window conflict / day /\nlow-opportunity"]
    DESTROY --> PARTIAL["partial solution + removed customers"]

    PARTIAL --> SELECTR["roulette repair operator"]
    SELECTR --> REPAIR["repair_operators\ncheapest / regret2 / regret3 /\nopportunity-cost / early-day /\nslack-aware"]
    REPAIR --> CAND["candidate solution"]

    CAND --> LS{"local_search enabled?"}
    LS -->|"yes"| IMP["local_search.improve()\nrelocate earlier day, relocate, 2-opt"]
    LS -->|"no"| EVAL
    IMP --> EVAL["objective.evaluate_solution()"]

    EVAL --> ACCEPT{"Simulated annealing accept?"}
    ACCEPT -->|"accepted"| CURRENT
    ACCEPT -->|"rejected"| CURRENT
    EVAL --> BEST{"new best?"}
    BEST -->|"yes"| BESTSOL["update best solution"]
    BEST -->|"no"| WEIGHTS["operator score update"]
    BESTSOL --> WEIGHTS
    WEIGHTS --> STOP{"stop / early stop / prune?"}
    STOP -->|"continue"| SELECTD
    STOP -->|"done"| OUT["best solution + histories"]
```

## 4. Opportunity Cost Subgraph

```mermaid
flowchart TD
    OCI["repair_operators.opportunity_cost_insertion()"] --> POS["best_insertion_positions()"]
    POS --> DELTA["insertion_delta()"]
    DELTA --> ROUTE["evaluate_route()"]

    OCI --> OC{"tune_light?"}
    OC -->|"false"| FOC["compute_feasibility_opportunity_cost()"]
    FOC --> TODAY["_best_cost_for_days(today)"]
    FOC --> FUTURE["_best_cost_for_days(future days)"]
    TODAY --> POS
    FUTURE --> POS

    OC -->|"true"| OIDX["compute_opportunity_index()\ncheap screening score"]
    OCI --> LATE["compute_postponement_increment()"]
    FOC --> ADJ["adjusted insertion cost"]
    OIDX --> ADJ
    LATE --> ADJ
    ADJ --> INSERT["apply_insertion()"]
```

Why this matters:

- Full mode uses exact insertion-based feasibility opportunity cost.
- `--tune-light` uses a cheaper opportunity index during screening so large searches do not get stuck inside nested future insertion checks.
- Feasibility remains exact because every actual insertion still calls `evaluate_route()`.

## 5. Tuning Pipeline

```mermaid
flowchart TD
    PIPE["scripts/run_tuning_pipeline.ps1\nor run_tuning_pipeline.cmd"] --> Q["Stage 1\nquick debug"]
    Q --> S["Stage 2\nscreening random search\n--tune-light"]
    S --> F["Stage 3\nfocused tuning"]
    F --> B["outputs/tuning/best_config.json"]
    B --> V["Stage 4\nvalidation unseen seeds"]
    V --> C["Stage 5\nfinal fair comparison"]

    S --> RAW["tuning_results_raw.csv"]
    S --> CKPT["tuning_checkpoints.csv"]
    F --> RAW
    F --> CKPT
    RAW --> SUM["tuning_results_summary.csv"]
    SUM --> TOP["top_10_configs.csv"]
    SUM --> B
    C --> FINAL["final_method_comparison.csv\nfinal_method_comparison_summary.csv"]
```

## 6. Module Dependency Overview

```mermaid
flowchart LR
    main --> data_loader
    main --> distance
    main --> feasibility
    main --> experiments
    main --> tuning
    main --> parameter_grid
    main --> baselines
    main --> alns

    experiments --> baselines
    experiments --> initial_solution
    experiments --> alns
    experiments --> reporting

    tuning --> parameter_grid
    tuning --> initial_solution
    tuning --> alns
    tuning --> tuning_report

    alns --> destroy_operators
    alns --> repair_operators
    alns --> local_search
    alns --> objective
    alns --> utils

    baselines --> feasibility
    baselines --> initial_solution
    baselines --> objective

    initial_solution --> feasibility
    initial_solution --> objective
    initial_solution --> opportunity_cost

    destroy_operators --> feasibility
    destroy_operators --> opportunity_cost

    repair_operators --> feasibility
    repair_operators --> opportunity_cost
    repair_operators --> objective

    local_search --> feasibility
    local_search --> objective

    feasibility --> models
    objective --> models
    reporting --> utils
```

## 7. Important Outputs

```mermaid
flowchart TD
    RUN["main.py"] --> OUT["outputs/"]
    OUT --> MET["metrics/"]
    OUT --> SCH["schedules/"]
    OUT --> LOG["logs/alns_run.log"]
    OUT --> TUN["tuning/"]

    MET --> RC["results_comparison.csv"]
    MET --> DRS["daily_route_summary.csv"]
    MET --> FMC["final_method_comparison.csv"]
    MET --> FMCS["final_method_comparison_summary.csv"]

    SCH --> BS["best_schedule.csv"]
    SCH --> SM["schedule_*.csv"]
    SCH --> UND["undelivered_orders.csv"]

    TUN --> RAW["tuning_results_raw.csv"]
    TUN --> CKPT["tuning_checkpoints.csv"]
    TUN --> TS["tuning_results_summary.csv"]
    TUN --> BEST["best_config.json"]
```

## 8. Reading Guide

- Start at `main.py` to understand execution modes.
- Follow `data_loader.py`, `distance.py`, and `feasibility.py` for problem preprocessing and constraints.
- Read `objective.py` before interpreting any comparison CSV.
- Read `initial_solution.py`, `destroy_operators.py`, `repair_operators.py`, and `alns.py` for the optimizer core.
- Read `tuning.py`, `parameter_grid.py`, and `tuning_report.py` for staged/random tuning.
- Read `reporting.py` for what gets exported and how route distance is reconciled with schedules.
