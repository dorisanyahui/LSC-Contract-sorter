from __future__ import annotations

from rapidfuzz import fuzz, process


class AliasMatcher:
    """Fuzzy string matcher for company name aliases using rapidfuzz."""

    def match(
        self,
        name: str,
        candidates: list[str],
        threshold: float = 80.0,
    ) -> str | None:
        """Find the best match for name in candidates list.

        Returns the matched string if score >= threshold, else None.
        """
        if not name or not candidates:
            return None

        result = process.extractOne(
            name,
            candidates,
            scorer=fuzz.ratio,
            score_cutoff=threshold,
        )

        if result is not None:
            matched_str, score, _ = result
            return matched_str

        return None

    def match_any(
        self,
        name: str,
        candidates_map: dict[str, list[str]],
        threshold: float = 80.0,
    ) -> str | None:
        """Find the best match across multiple candidate lists.

        candidates_map: dict mapping group_name -> list of company names/aliases
        Returns the group_name of the best match, or None.
        """
        if not name or not candidates_map:
            return None

        best_group: str | None = None
        best_score: float = -1.0

        for group_name, aliases in candidates_map.items():
            if not aliases:
                continue

            result = process.extractOne(
                name,
                aliases,
                scorer=fuzz.ratio,
                score_cutoff=threshold,
            )

            if result is not None:
                _, score, _ = result
                if score > best_score:
                    best_score = score
                    best_group = group_name

        return best_group
