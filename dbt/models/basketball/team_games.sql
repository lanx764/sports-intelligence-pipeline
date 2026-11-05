with home_side as (
    select
        match_id,
        kickoff_at,
        match_date,
        country,
        league_id,
        league,
        season,
        home_club_id            as club_id,
        away_club_id            as opponent_club_id,
        home_team               as team,
        away_team               as opponent,
        true                    as is_home,
        home_points_regulation  as regulation_points_scored,
        away_points_regulation  as regulation_points_conceded,
        home_points_final       as final_points_scored,
        away_points_final       as final_points_conceded,
        home_q1                 as q1_points_scored,
        away_q1                 as q1_points_conceded,
        home_q2                 as q2_points_scored,
        away_q2                 as q2_points_conceded,
        home_q3                 as q3_points_scored,
        away_q3                 as q3_points_conceded,
        home_q4                 as q4_points_scored,
        away_q4                 as q4_points_conceded,
        home_h1                 as h1_points_scored,
        away_h1                 as h1_points_conceded,
        home_h2                 as h2_points_scored,
        away_h2                 as h2_points_conceded,
        total_q1,
        total_q2,
        total_q3,
        total_q4,
        total_h1,
        total_h2,
        total_points
    from {{ ref('stg_basketball__games') }}
),

away_side as (
    select
        match_id,
        kickoff_at,
        match_date,
        country,
        league_id,
        league,
        season,
        away_club_id            as club_id,
        home_club_id            as opponent_club_id,
        away_team               as team,
        home_team               as opponent,
        false                   as is_home,
        away_points_regulation  as regulation_points_scored,
        home_points_regulation  as regulation_points_conceded,
        away_points_final       as final_points_scored,
        home_points_final       as final_points_conceded,
        away_q1                 as q1_points_scored,
        home_q1                 as q1_points_conceded,
        away_q2                 as q2_points_scored,
        home_q2                 as q2_points_conceded,
        away_q3                 as q3_points_scored,
        home_q3                 as q3_points_conceded,
        away_q4                 as q4_points_scored,
        home_q4                 as q4_points_conceded,
        away_h1                 as h1_points_scored,
        home_h1                 as h1_points_conceded,
        away_h2                 as h2_points_scored,
        home_h2                 as h2_points_conceded,
        total_q1,
        total_q2,
        total_q3,
        total_q4,
        total_h1,
        total_h2,
        total_points
    from {{ ref('stg_basketball__games') }}
),

both_sides as (
    select * from home_side
    union all
    select * from away_side
)

select
    *,
    final_points_scored > final_points_conceded as won
from both_sides