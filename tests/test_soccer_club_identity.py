"""Crucial fixture crosswalk behavior, not a global name-only identity join."""
import pytest

from sports_analyst.datasets.soccer.club_identity import same_club, normalized_name
from sports_analyst.datasets.soccer.enrichment import fixture_matches
from sports_analyst.datasets.soccer.understat import fixture_match


@pytest.mark.parametrize('first,second', [
    ('Bodø/Glimt','Bodo/Glimt'), ('ŁKS Łódź','LKS Lodz'), ('İstanbul Başakşehir','Istanbul Basaksehir'),
    ('FC København','FC Kobenhavn'), ('Malmö FF','Malmo FF'), ('São Paulo','Sa\u0303o Paulo'),
    ('Bayern München','Bayern Munich'), ('FK Crvena Zvezda','Red Star Belgrade'),
    ('FK Qarabag','Qarabag FK'), ('Internazionale','Inter'), ('Feyenoord Rotterdam','Feyenoord'),
])
def test_corroborated_fixture_matches_share_unicode_and_reviewed_alias_rules(first, second):
    fixture = {'event_id':'e1', 'date':'2025-09-01', 'home_team':first, 'away_team':'Recorded Opponent',
        'home_score':2, 'away_score':1, 'competition':'uefa.champions'}
    native = {'home':{'name':second,'score':2}, 'away':{'name':'Recorded Opponent','score':1},
        'status':{'utcTime':'2025-09-01', 'finished':True}}
    assert fixture_matches(native,fixture)
    fixture.update(home_team_id='1',away_team_id='2')
    understat = {'game_id':'u1','date':'2025-09-01','is_result':True,
        'home_team_id':'native1','away_team_id':'native2','home_team':second,'away_team':'Recorded Opponent',
        'home_goals':2,'away_goals':1}
    assert fixture_match(understat, fixture)
    assert not fixture_matches(native,{**fixture,'date':'2025-09-02'})
    assert not fixture_matches(native,{**fixture,'home_score':3})


def test_distinct_squads_ambiguous_short_names_and_missing_names_stay_unmatched():
    for first, second in [('Manchester City','Manchester United'), ('Inter','Inter Miami'),
        ('Bayern Munich','Bayern München U19'), ('Bayern Munich','Bayern München Women'),
        ('AS Monaco','Monaco II'), ('FC United of Manchester','Manchester United'), ('',''), (None,None)]:
        assert not same_club(first,second,'uefa.champions')
    assert not same_club('Inter','Internazionale','usa.1')
    assert normalized_name(None) == ''
    assert normalized_name('Bayern München') == normalized_name('BAYERN MU\u0308NCHEN')
