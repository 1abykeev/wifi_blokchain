"""
Persistence layer — saves and loads the blockchain to/from
data/blockchain.json.

Usage (called by app.py via monkey-patch on mine_pending_transactions):
    from persistence import save_chain, load_chain
    load_chain(switch.blockchain)   # at startup
    # save_chain is called automatically after every mine
"""

import json
import logging
from pathlib import Path

from blockchain import Block, Blockchain

logger = logging.getLogger("persistence")

DATA_DIR = Path(__file__).parent / "data"
CHAIN_FILE = DATA_DIR / "blockchain.json"


def save_chain(blockchain: Blockchain) -> None:
    """Serialize the full chain to data/blockchain.json."""
    DATA_DIR.mkdir(exist_ok=True)
    try:
        with open(CHAIN_FILE, "w") as fh:
            json.dump(blockchain.get_chain_as_list(), fh, indent=2)
    except OSError as exc:
        logger.error("Could not save chain: %s", exc)


def load_chain(blockchain: Blockchain) -> bool:
    """
    Replace blockchain.chain with blocks read from disk.
    Returns True on success, False if no saved file exists.
    The genesis block created by Blockchain.__init__ is discarded
    when a persisted chain is found.
    """
    if not CHAIN_FILE.exists():
        logger.info("No saved chain found — starting fresh")
        return False

    try:
        with open(CHAIN_FILE) as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not load chain: %s", exc)
        return False

    blocks = []
    for d in raw:
        b = Block.__new__(Block)
        b.index = d["index"]
        b.timestamp = d["timestamp"]
        b.transactions = d["transactions"]
        b.previous_hash = d["previous_hash"]
        b.nonce = d["nonce"]
        b.hash = d["hash"]
        blocks.append(b)

    blockchain.chain = blocks
    blockchain.pending_transactions = []
    logger.info("Loaded %d block(s) from disk", len(blocks))
    return True
