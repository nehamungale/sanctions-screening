"""Name blocking over the Stage 1 exact-part index.

``index_name_part_record_id.json`` maps one normalised part to record ids.
Variant groups and edit distance are applied here, to those keys only.
The person-level ``index_name.json`` is not read: it can contain the verified
legal name, which search must not use.
"""

from __future__ import annotations

from stage1.normalise import NameTools


class PartBlock:
    """Candidate records for a screened name, from exact parts plus expansion."""

    def __init__(self, index: dict[str, tuple[str, ...]], names: NameTools):
        self.index = {key: value for key, value in index.items() if key}
        self.names = names
        self.keys = tuple(sorted(self.index))
        self._match_cache: dict[str, tuple[str, ...]] = {}
        self._candidate_cache: dict[tuple[str, ...], tuple[str, ...]] = {}

    def candidates(self, parts: tuple[str, ...]) -> tuple[str, ...]:
        """Record ids that might agree with ``parts``. Confirmation is separate."""
        if not parts:
            return ()
        cached = self._candidate_cache.get(parts)
        if cached is not None:
            return cached
        found: set[str] = set()
        probes = list(parts)
        probes.extend(left + right for left, right in zip(parts, parts[1:]))
        for probe in probes:
            for key in self._keys_matching(probe):
                found.update(self.index[key])
        for token in parts:
            self._add_token_splits(token, found)
        for left, right in zip(parts, parts[1:]):
            for key in self.keys:
                if self._key_splits_into(key, left, right):
                    found.update(self.index[key])
        result = tuple(sorted(found))
        self._candidate_cache[parts] = result
        return result

    def _keys_matching(self, token: str) -> tuple[str, ...]:
        """Index keys that agree with ``token`` (exact, variant, or edit distance)."""
        if not token:
            return ()
        cached = self._match_cache.get(token)
        if cached is not None:
            return cached
        matched = tuple(key for key in self.keys if self.names.parts_match(token, key))
        self._match_cache[token] = matched
        return matched

    def _add_token_splits(self, token: str, found: set[str]) -> None:
        """A screened token written across two record parts (abdulsalam / abdul + salam)."""
        if len(token) < 2:
            return
        for split in range(1, len(token)):
            left_keys = self._keys_matching(token[:split])
            right_keys = self._keys_matching(token[split:])
            if not left_keys or not right_keys:
                continue
            left_ids: set[str] = set()
            for key in left_keys:
                left_ids.update(self.index[key])
            right_ids: set[str] = set()
            for key in right_keys:
                right_ids.update(self.index[key])
            found.update(left_ids & right_ids)

    def _key_splits_into(self, key: str, left: str, right: str) -> bool:
        """An indexed part written apart in the screened name (josephsmith / joe + smith)."""
        if len(key) < 2:
            return False
        for split in range(1, len(key)):
            if self.names.parts_match(key[:split], left) and self.names.parts_match(key[split:], right):
                return True
        return False
