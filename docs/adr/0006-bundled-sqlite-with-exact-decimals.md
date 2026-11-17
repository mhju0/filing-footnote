# Bundled SQLite File with Exact Decimals

Status: Accepted · 2026-11-17 (D66) · Supersedes the floating-point year-over-year path

The app reads a read-only SQLite file built on the owner's Mac and bundled with the app; a small read-only API serves the same file. Monetary amounts and ratios are stored as decimal strings and calculated with exact decimal arithmetic, never binary floating point, so a figure on screen equals the figure in the filing and a percentage change can be reproduced by hand. This replaces the year-over-year path that used floating-point numbers. This was chosen over the PostgreSQL and pgvector service at run time because the app must work offline at no running cost, and over storing numbers as floats because rounding drift would make a stated figure differ from the filed one.
