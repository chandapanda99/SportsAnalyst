# Football special-teams diagrams

The shared NFL/CFB tablet renders field goals, extra points, punts and kickoffs as
kick/return diagrams. It does not substitute a normal offensive formation or infer
a full coverage/blocking unit. Recorded specialists are identified where supplied;
unnamed markers remain generic. Lateral positions and curved paths are illustrative.

NFL game evidence preserves the kick type, specialist names, kick and return
distances, result, and relevant touchback/fair-catch/block flags. nflverse kickoff
possession refers to the receiving team: its start yardline is converted to the
kicking team's direction before drawing. Other scrimmage kicks retain their
recorded possession orientation. Goal-kick distances locate the illustrative kick
origin relative to the back-of-end-zone posts, rather than treating the distance
as line-of-scrimmage yardage. Punter depth is illustrative; punt distance remains
measured from scrimmage.

CFB uses recorded ESPN start/end context and specialist roles. Available
SportsDataverse `yds_punted`, `yds_punt_return`, `yds_fg`, `yds_kickoff` and
`yds_kickoff_return` values are retained as provider-derived narrative context.
Explicit narrative distances also support older cached plays and saved reports.
Net play yardage never substitutes for kick or return distance. The render cache
version is incremented to refresh previously normalized games without changing
saved EPA/WPA or analysis measurements.

Kick flight travels toward the receiving goal; recorded returns travel back toward
the kicking goal. Touchbacks, fair catches, downed kicks and out-of-bounds kicks
do not get return arrows. A touchback placement marker requires an explicit
recorded end spot or a team-verified narrative placement; no rule-dependent spot
is guessed from sport or season. Blocked, nullified, or unlocated attempts do not
receive invented completed flight paths. Missed field goals show the recorded
outcome and reference posts without inventing the lateral miss or landing point.

No new source, tracking feed, model call, or paid service is required. Restart the
backend and reload the rebuilt frontend; desktop installations require rebuilding
their bundle to include these changes.
