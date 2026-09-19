from __future__ import annotations
from abc import ABC, abstractmethod
from collections import Counter


class SourceAdapter(ABC):
    adapter_name = "base"

    def __init__(self):
        self.stats = Counter()

    @abstractmethod
    async def run(self, client, cases):
        ...
