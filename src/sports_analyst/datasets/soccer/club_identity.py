"""Versioned club-name equivalence, corroborated by fixture context and unique IDs.

These keys assist crosswalks; they are never replacement provider team IDs.
No fuzzy matching, suffix stripping, or automatic translation is performed.
"""
import unicodedata

VERSION = "soccer-club-names-1"


def normalized_name(value):
    if not isinstance(value, str) or not value.strip():
        return ""
    # NFKD handles combining accents, but these Latin letters do not decompose.
    value = value.casefold().translate(str.maketrans({"ø":"o", "ł":"l", "đ":"d", "ð":"d", "þ":"th", "æ":"ae", "œ":"oe", "ı":"i"}))
    return "".join(c for c in unicodedata.normalize("NFKD", value) if c.isalnum())


# Reviewed ESPN/FotMob pairs observed in cached competition fixtures, plus
# existing reviewed Understat aliases. Short names are competition-scoped.
_GROUPS = [
    ({"ger.1", "uefa.champions"}, ("Bayern Munich", "Bayern München", "FC Bayern München", "Bayern Muenchen", "FC Bayern Munich")),
    ({"eng.1", "uefa.champions"}, ("Manchester City", "Man City")),
    ({"eng.1", "uefa.champions"}, ("Manchester United", "Manchester Utd", "Man Utd")),
    ({"eng.1", "uefa.champions"}, ("Tottenham Hotspur", "Tottenham")),
    ({"eng.1", "uefa.champions"}, ("Wolverhampton Wanderers", "Wolverhampton", "Wolves")),
    ({"eng.1", "uefa.champions"}, ("Brighton & Hove Albion", "Brighton and Hove Albion", "Brighton Hove Albion", "Brighton")),
    ({"eng.1", "uefa.champions"}, ("Newcastle United", "Newcastle")),
    ({"ger.1", "uefa.champions"}, ("1. FC Union Berlin", "Union Berlin")),
    ({"ita.1", "uefa.champions"}, ("AC Milan", "Milan")),
    ({"ita.1", "uefa.champions"}, ("Internazionale", "Inter", "Inter Milan")),
    ({"ita.1", "uefa.champions"}, ("Napoli", "SSC Napoli")),
    ({"ita.1", "uefa.champions"}, ("AS Roma", "Roma")),
    ({"fra.1", "uefa.champions"}, ("AS Monaco", "Monaco")),
    ({"uefa.champions"}, ("Ajax Amsterdam", "Ajax")),
    ({"uefa.champions"}, ("Feyenoord Rotterdam", "Feyenoord")),
    ({"uefa.champions"}, ("Antwerp", "Royal Antwerp")),
    ({"uefa.champions"}, ("FK Qarabag", "Qarabag FK")),
    ({"uefa.champions"}, ("LASK Linz", "LASK")),
    ({"uefa.champions"}, ("Pafos", "Pafos FC")),
    ({"uefa.champions"}, ("RB Salzburg", "Salzburg")),
    ({"uefa.champions"}, ("Red Star Belgrade", "FK Crvena Zvezda")),
    ({"uefa.champions"}, ("SK Sturm Graz", "Sturm Graz")),
    ({"uefa.champions"}, ("Viking FK", "Viking")),
]


def club_key(value, competition=None):
    key = normalized_name(value)
    if not key:
        return ""
    matches = {normalized_name(names[0]) for scopes, names in _GROUPS
               if competition in scopes and key in {normalized_name(name) for name in names}}
    # Future alias additions must not silently pick a club if the registry conflicts.
    return next(iter(matches)) if len(matches) == 1 else key if not matches else ""


def same_club(first, second, competition=None):
    key = club_key(first, competition)
    return bool(key) and key == club_key(second, competition)
