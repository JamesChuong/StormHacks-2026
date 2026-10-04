"""Hooks for the Solana betting program (solana/programs/arena_betting).

These are stubs that log what would be sent on-chain. Wire them to the
deployed program with solana-py/anchorpy and SOLANA_ORCHESTRATOR_KEYPAIR.
"""
import logging

log = logging.getLogger(__name__)


def create_match(match_id, commit_hash, num_agents):
    log.info("[chain] create_match id=%s commit=%s agents=%s", match_id, commit_hash, num_agents)


def lock(match_id):
    log.info("[chain] lock id=%s", match_id)


def resolve(match_id, winner_index, reveal_hash):
    log.info("[chain] resolve id=%s winner=%s reveal=%s", match_id, winner_index, reveal_hash)
