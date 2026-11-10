{#
    team_form: one row per team per game.
    Every statistic is calculated only from the team's previous games (strictly before this game's kickoff).
    Change n to use a different number of games, decimals to change rounding.
    Add a measure: add one line to `measures`. Add a statistic: see macros/form_stats.sql.
#}
{% set n = 5 %}
{% set decimals = 2 %}
{% set measures = [
    {'name': 'points_scored_regulation',   'source': 'regulation_points_scored'},
    {'name': 'points_conceded_regulation', 'source': 'regulation_points_conceded'},
    {'name': 'game_total_regulation',      'source': 'total_points'},
    {'name': 'points_scored_q1',   'source': 'q1_points_scored'},
    {'name': 'points_conceded_q1', 'source': 'q1_points_conceded'},
    {'name': 'game_total_q1',      'source': 'total_q1'},
    {'name': 'points_scored_q2',   'source': 'q2_points_scored'},
    {'name': 'points_conceded_q2', 'source': 'q2_points_conceded'},
    {'name': 'game_total_q2',      'source': 'total_q2'},
    {'name': 'points_scored_q3',   'source': 'q3_points_scored'},
    {'name': 'points_conceded_q3', 'source': 'q3_points_conceded'},
    {'name': 'game_total_q3',      'source': 'total_q3'},
    {'name': 'points_scored_q4',   'source': 'q4_points_scored'},
    {'name': 'points_conceded_q4', 'source': 'q4_points_conceded'},
    {'name': 'game_total_q4',      'source': 'total_q4'},
    {'name': 'points_scored_h1',   'source': 'h1_points_scored'},
    {'name': 'points_conceded_h1', 'source': 'h1_points_conceded'},
    {'name': 'game_total_h1',      'source': 'total_h1'},
    {'name': 'points_scored_h2',   'source': 'h2_points_scored'},
    {'name': 'points_conceded_h2', 'source': 'h2_points_conceded'},
    {'name': 'game_total_h2',      'source': 'total_h2'}
] %}

with windowed as (
    select
        match_id,
        club_id,
        opponent_club_id,
        team,
        opponent,
        is_home,
        kickoff_at,
        match_date,
        country,
        league_id,
        league,
        season,
        count(*) over previous_games as games_used,
        first_value(match_date) over previous_games as oldest_game_date,
        {%- for m in measures %}
        array_agg({{ m.source }}) over previous_games as {{ m.name }}_previous_games{{ ',' if not loop.last }}
        {%- endfor %}
    from {{ ref('team_games') }}
    window previous_games as (
        partition by club_id
        order by kickoff_at, match_id
        rows between {{ n }} preceding and 1 preceding
    )
)

select
    w.match_id,
    w.club_id,
    w.opponent_club_id,
    w.team,
    w.opponent,
    w.is_home,
    w.kickoff_at,
    w.match_date,
    w.country,
    w.league_id,
    w.league,
    w.season,
    w.games_used,
    w.oldest_game_date,
    w.match_date - w.oldest_game_date as days_since_oldest_game,
    {%- for m in measures %}
    {{ form_stats_select(m.name, n, decimals) }}{{ ',' if not loop.last }}
    {%- endfor %}
from windowed as w
{%- for m in measures %}
{{ form_stats_join(m.name, n, decimals) }}
{%- endfor %}
