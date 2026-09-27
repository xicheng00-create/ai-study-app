"""UNI-MASTER 边界、证据与历史空主题回归。"""
from ai import mastery


def test_boundaries():
    assert mastery.mastery_state(None, 0, 0, 0) == 'na'
    assert mastery.mastery_state(49, 2, 4, 1) == 'weak'
    assert mastery.mastery_state(50, 2, 4, 1) == 'progress'
    assert mastery.mastery_state(79, 2, 4, 1) == 'progress'
    assert mastery.mastery_state(80, 1, 4, 1) == 'progress'
    assert mastery.mastery_state(80, 2, 4, 1) == 'master'
    assert mastery.mastery_state(100, 3, 20, 20) == 'progress'
    assert mastery.mastery_state(100, 4, 20, 20) == 'master'


def test_rollup_and_class():
    cards = [dict(state=s, m=m, evidence=e) for s, m, e in (
        ('mastered', 100, True), ('learning', 20, True),
        ('new', 0, False), ('new', 0, False))]
    result = mastery.rollup(cards)
    assert (result['m'], result['coverage'], result['evidence_cards']) == (60, 50, 2)
    assert mastery.rollup(cards[2:])['m'] is None
    agg = mastery.class_mastery([result, mastery.rollup(cards[2:])])
    assert agg == {'m': 60, 'coverage': 25, 'assessed': 1, 'total': 2}
