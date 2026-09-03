"""FPL Squad Optimizer.

Deliberately empty of imports. The CLI pulls in the training stack
(LightGBM, pandas), which the API server neither needs nor can load — the
slim runtime image has no libgomp for LightGBM to link against. Importing
the CLI here would drag that chain into every `import fpl_optimizer.api`
and crash the server at boot.

Console scripts point at `fpl_optimizer.cli:main` directly.
"""
