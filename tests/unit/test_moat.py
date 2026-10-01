from __future__ import annotations


def test_no_segment_mapping_is_an_explicit_moat_evidence_gap(db):
    from equitylens.domain.moat import moat_signals

    result = moat_signals(db, "0000000991", "NOSEG")

    gap = next(
        item for item in result["qualitative_gaps"]
        if item["dimension"] == "分部/产品收入依赖"
    )
    assert gap["status"] == "EVIDENCE_GAP"
    assert gap["reason"]
    assert gap["next_evidence"]
    assert not any(signal["dimension"] == "收入依赖" for signal in result["signals"])
