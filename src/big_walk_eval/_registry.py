# Entry point for Inspect's registry, so `inspect eval big_walk_eval/big_walk_coop` works.
from big_walk_eval.task import big_walk_coop

__all__ = ["big_walk_coop"]
