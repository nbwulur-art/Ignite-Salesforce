# Lead Prioritization & Smart Routing Engine
**2026 Ignite Design Challenge — Salesforce**

## Overview
An automated routing engine built to process high-volume, messy sales datasets. The application ingests raw customer lead and sales representative CSVs, standardizes inconsistent data formats, and 
calculates priority scores using business rules and VIP overrides, and dispatches leads to optimal representatives based on multi-skill matching, seniority constraints, and workload balancing.
Results are surfaced on an interactive, manager-facing dashboard.

---

## Core Capabilities
* **Data Sanitization & Fallback Handling:** Programmatically cleans casing, resolves unstandardized aliases, and applies deterministic fallbacks for missing or malformed fields so zero leads are dropped.
* **Rule-Based Priority Scoring:** Evaluates company size, recent activity, and industry vertical to categorize leads into **Critical**, **High**, **Medium**, or **Low** tiers—with immediate **Critical** overrides for `VIP_Referral` flags.
* **Constraint-Aware Multi-Skill Routing:** Matches leads strictly on **Region**, **Language**, and **Industry Vertical**, enforcing seniority gates (preventing Junior reps from receiving Critical leads) and strict maximum capacity caps.
* **Load-Balanced Allocation:** Distributes tied eligible reps evenly using [Insert Chosen Algorithm, e.g., Least-Loaded / Round-Robin Scheduling] and routes unassignable overflow leads to a dedicated **Manager Review** queue.
* **High-Throughput Scale Engine:** Processes both the 100-lead sample dataset and the 50,000-lead scale benchmark in memory with sub-second/low-latency execution.
* **Manager Dashboard:** Interactive UI featuring on-demand dataset execution, state reset controls, system health KPIs, filterable lead queues, and rep capacity utilization trackers.

