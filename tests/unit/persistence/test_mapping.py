from nexus.domain.spread import EvaluationStatus, TransferQuote, TransferStatus
from nexus.persistence.repositories import evaluation_to_row, row_to_evaluation
from tests.support import make_evaluation


def test_roundtrip_with_breakdown() -> None:
    evaluation = make_evaluation(fees_estimated=True)
    assert row_to_evaluation(evaluation_to_row(evaluation)) == evaluation


def test_roundtrip_without_breakdown() -> None:
    evaluation = make_evaluation(
        status=EvaluationStatus.INSUFFICIENT_DEPTH,
        with_breakdown=False,
        transfer=TransferQuote(TransferStatus.UNKNOWN, note="no source transfer metadata"),
    )
    restored = row_to_evaluation(evaluation_to_row(evaluation))
    assert restored == evaluation
    assert restored.breakdown is None
