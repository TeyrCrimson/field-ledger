"""Movement log: an offline, append-only record of where field kit is.

Layers (each module only depends on the ones above it):
    model     data types
    ids       ID and location canonicalisation rules
    parse     text grammar -> Command
    state     events -> current state (pure fold)
    validate  Command + state -> Verdict (pure)
    store     SQLite persistence, merge
    cli       argparse adapter
"""
