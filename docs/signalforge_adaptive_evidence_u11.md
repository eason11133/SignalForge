# SignalForge Adaptive Evidence U11

Purpose: make repeated evidence acquisition learn from actual novel-yield instead of replaying fixed source/query order.

Adopted mature methods:
- relevance-feedback style query reformulation
- MMR-style relevance/diversity selection
- empirical adapter-yield priors with smoothing

Truth boundary: acquisition efficiency changes where SignalForge looks next. It never upgrades supply to demand, single evidence to recurrence, WTP, or market validation.
