# onboarding_brief.md

- run_id: `a5d06a3850c74f089ff37107dec3513b`
- repo_ref: `/Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic`
- generated_at: `2026-03-14T05:55:05+00:00`

## Five FDE Day-One Answers

1) **Primary data ingestion path**
Best-effort sources: dataset:customer_orders, dataset:customer_payments, dataset:final, dataset:payments, dataset:raw_customers

2) **3-5 most critical output datasets/endpoints**
Best-effort sinks: dataset:query_log

3) **Blast radius of the most critical module**
Critical module candidate: /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/dbt_project.yml

4) **Where business logic is concentrated vs distributed**
See CODEBASE critical hubs and module purpose index for concentration signals.

5) **What changed most in the last 90 days**
High-velocity files: /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/dbt_project.yml, /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/models/schema.yml, /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/models/customers.sql, /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/models/orders.sql, /Users/melkam/Documents/10 Academy/Week4/jaffle-shop-classic/logs/query_log.sql

## Evidence
- `.cartography/module_graph.json` (module graph, velocity, hubs)
- `.cartography/lineage_graph.json` (sources/sinks, dependency graph)
- `.cartography/semantic_index/day_one_answers.json` (semantic synthesis when available)
