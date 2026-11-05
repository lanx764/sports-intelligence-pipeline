select
    match_id,
    match_date,
    (match_date + match_time)  as kickoff_at,

    country,
    league_id,
    league,
    season,

    home_club_id,
    away_club_id,
    home_team,
    away_team,

    home_q1, home_q2, home_q3, home_q4,
    away_q1, away_q2, away_q3, away_q4,
    home_h1, home_h2,
    away_h1, away_h2,

    home_total  as home_points_regulation,
    away_total  as away_points_regulation,
    home_final  as home_points_final,
    away_final  as away_points_final,

    total_q1, total_q2, total_q3, total_q4,
    total_h1, total_h2,
    total_points
from {{ source('basketball', 'fact_games') }}