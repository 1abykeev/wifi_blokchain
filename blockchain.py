import hashlib
import json
import time
from typing import List, Dict, Any, Optional


class Block:
    def __init__(
        self,
        index: int,
        transactions: List[Dict[str, Any]],
        previous_hash: str,
        timestamp: Optional[float] = None,
    ):
        self.index = index
        self.timestamp = timestamp or time.time()
        self.transactions = transactions
        self.previous_hash = previous_hash
        self.nonce = 0
        self.hash = self.compute_hash()

    def compute_hash(self) -> str:
        # Exclude the 'hash' field itself so re-computation is stable
        block_dict = {k: v for k, v in self.__dict__.items() if k != "hash"}
        block_string = json.dumps(block_dict, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "timestamp": self.timestamp,
            "transactions": self.transactions,
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
            "hash": self.hash,
        }


class Blockchain:
    DIFFICULTY = 2  # Number of leading zeros required in hash

    def __init__(self):
        self.chain: List[Block] = []
        self.pending_transactions: List[Dict[str, Any]] = []
        self._create_genesis_block()

    def _create_genesis_block(self):
        genesis = Block(
            index=0,
            transactions=[{"type": "genesis", "data": "WiFi Blockchain Genesis Block"}],
            previous_hash="0" * 64,
            timestamp=time.time(),
        )
        genesis.hash = self._proof_of_work(genesis)
        self.chain.append(genesis)

    def _proof_of_work(self, block: Block) -> str:
        block.nonce = 0
        computed = block.compute_hash()
        while not computed.startswith("0" * self.DIFFICULTY):
            block.nonce += 1
            computed = block.compute_hash()
        return computed

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def add_transaction(self, transaction: Dict[str, Any]) -> int:
        """Add a transaction to pending pool. Returns pending count."""
        transaction["timestamp"] = time.time()
        self.pending_transactions.append(transaction)
        return len(self.pending_transactions)

    def mine_pending_transactions(self) -> Block:
        """Mine all pending transactions into a new block."""
        if not self.pending_transactions:
            raise ValueError("No pending transactions to mine")

        block = Block(
            index=len(self.chain),
            transactions=self.pending_transactions.copy(),
            previous_hash=self.last_block.hash,
        )
        block.hash = self._proof_of_work(block)
        self.chain.append(block)
        self.pending_transactions = []
        return block

    def add_transaction_and_mine(self, transaction: Dict[str, Any]) -> Block:
        """Convenience: add a single transaction and immediately mine it."""
        self.add_transaction(transaction)
        return self.mine_pending_transactions()

    def is_chain_valid(self) -> bool:
        for i in range(1, len(self.chain)):
            current = self.chain[i]
            previous = self.chain[i - 1]

            if current.hash != current.compute_hash():
                return False

            if current.previous_hash != previous.hash:
                return False

        return True

    def get_chain_as_list(self) -> List[Dict[str, Any]]:
        return [block.to_dict() for block in self.chain]

    def get_transactions_by_type(self, tx_type: str) -> List[Dict[str, Any]]:
        results = []
        for block in self.chain:
            for tx in block.transactions:
                if tx.get("type") == tx_type:
                    results.append({**tx, "block_index": block.index})
        return results
