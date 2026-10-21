# Data quality report

| check | status | detail |
|---|---|---|
| tables not empty | OK | 64 matches, 234637 events |
| every match has events | OK | 0 matches without events |
| event ids unique | OK | 0 duplicated ids |
| events reference known matches | OK | 0 orphan events |
| coordinates inside the 120x80 pitch | OK | 0 events outside |
| xG within [0, 1] | OK | 0 out of range, 0 shots without xG |
| goals from events match official scores | OK | 0 team-scores differ |
| 2 teams per lineup | OK | 0 matches with a different count |
| event players exist in players | OK | 0 unknown player ids |
| every shootout has a winner | OK | 0 shootouts without a winner |
| team_matches has 2 rows per match | OK | 128 rows for 64 matches |
