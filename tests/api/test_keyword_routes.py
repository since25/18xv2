from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.routes.keywords import scan_duplicate_keywords
from app.models.whitelist import WhitelistCandidate
from app.schemas.keywords import KeywordDuplicateScanRequest
from app.services.keywords.registry_service import KeywordRegistryService


def test_duplicate_scan_response_includes_reference_counts(db_session: Session):
    svc = KeywordRegistryService(db_session)
    first = svc.create_entry(canonical_name="Alpha", keyword_type="whitelist", aliases=["ABP31"])
    second = svc.create_entry(canonical_name="ABP-31", keyword_type="whitelist")
    db_session.add_all(
        [
            WhitelistCandidate(
                source_tid=4001,
                source_magnet="magnet:?xt=urn:btih:route-a",
                source_title="引用 A",
                matched_keyword_entry_id=first.id,
                matched_keyword=first.canonical_name,
                duplicate_status="clear",
                target_path="/target/a",
            ),
            WhitelistCandidate(
                source_tid=4002,
                source_magnet="magnet:?xt=urn:btih:route-b",
                source_title="引用 B",
                matched_keyword_entry_id=second.id,
                matched_keyword=second.canonical_name,
                duplicate_status="clear",
                target_path="/target/b",
            ),
            WhitelistCandidate(
                source_tid=4003,
                source_magnet="magnet:?xt=urn:btih:route-c",
                source_title="引用 C",
                matched_keyword_entry_id=second.id,
                matched_keyword=second.canonical_name,
                duplicate_status="clear",
                target_path="/target/c",
            ),
        ]
    )
    db_session.commit()

    response = scan_duplicate_keywords(
        KeywordDuplicateScanRequest(keyword_type="whitelist", threshold=0.85),
        db_session,
    )

    assert len(response.pairs) == 1
    pair = response.pairs[0]
    counts_by_id = {
        pair.keyword_1.id: pair.keyword_1_reference_count,
        pair.keyword_2.id: pair.keyword_2_reference_count,
    }
    assert counts_by_id == {first.id: 1, second.id: 2}
