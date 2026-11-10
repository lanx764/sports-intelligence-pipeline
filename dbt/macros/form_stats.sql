{#
    Form statistics, defined once.

    Every statistic below is calculated from the list of one measure's values in the
    previous games, oldest first, newest last (the name of that list is the placeholder __arr__).
    The values of that list are exposed as t.v (the value) and t.pos (its position, 1 = oldest).

    To add a statistic: add ONE entry to this list. Every measure in team_form gets it.
    n        = how many previous games are used
    decimals = how many decimals to keep on rounded statistics
#}
{% macro form_stat_definitions(n, decimals) %}
    {% set defs = [
        {'name': 'mean',
         'sql': 'round(avg(t.v), ' ~ decimals ~ ')'},
        {'name': 'median',
         'sql': '(percentile_cont(0.5) within group (order by t.v))::numeric'},
        {'name': 'mode',
         'sql': '(select x.v from (select y.v, count(*) as c from unnest(__arr__) as y(v) group by y.v) as x where x.c > 1 order by x.c desc, x.v limit 1)'},
        {'name': 'min',
         'sql': 'min(t.v)'},
        {'name': 'max',
         'sql': 'max(t.v)'},
        {'name': 'range',
         'sql': 'max(t.v) - min(t.v)'},
        {'name': 'sd',
         'sql': 'round(stddev_samp(t.v), ' ~ decimals ~ ')'},
        {'name': 'mad',
         'sql': '(select (percentile_cont(0.5) within group (order by abs(x.v - m.med)))::numeric from unnest(__arr__) as x(v) cross join lateral (select percentile_cont(0.5) within group (order by y.v) as med from unnest(__arr__) as y(v)) as m)'},
        {'name': 'linear_weighted_mean',
         'sql': 'round(sum(t.v * t.pos)::numeric / sum(t.pos), ' ~ decimals ~ ')'},
        {'name': 'exponential_weighted_mean',
         'sql': 'round(sum(t.v * power(0.5, ' ~ n ~ ' - t.pos)) / sum(power(0.5, ' ~ n ~ ' - t.pos)), ' ~ decimals ~ ')'},
        {'name': 'trimmed_mean',
         'sql': 'round((sum(t.v) - min(t.v) - max(t.v))::numeric / (count(t.v) - 2), ' ~ decimals ~ ')'},
        {'name': 'last_value',
         'sql': 'max(t.v) filter (where t.pos = ' ~ n ~ ')'},
        {'name': 'last_change',
         'sql': 'max(t.v) filter (where t.pos = ' ~ n ~ ') - max(t.v) filter (where t.pos = ' ~ (n - 1) ~ ')'},
        {'name': 'z_score',
         'sql': 'round((max(t.v) filter (where t.pos = ' ~ n ~ ') - avg(t.v) filter (where t.pos < ' ~ n ~ ')) / nullif(stddev_samp(t.v) filter (where t.pos < ' ~ n ~ '), 0), ' ~ decimals ~ ')'}
    ] %}
    {{ return(defs) }}
{% endmacro %}


{# One lateral join per measure: works out every statistic from that measure's list of previous values. #}
{# The statistics stay empty unless the list holds exactly n real values (fewer than n games, or missing scores). #}
{% macro form_stats_join(measure, n, decimals) %}
{%- set arr = 'w.' ~ measure ~ '_previous_games' -%}
left join lateral (
    select
    {%- for d in form_stat_definitions(n, decimals) %}
        {{ d.sql | replace('__arr__', arr) }} as {{ d.name }}{{ ',' if not loop.last }}
    {%- endfor %}
    from unnest({{ arr }}) with ordinality as t(v, pos)
    having count(t.v) = {{ n }}
) as {{ measure }}_s on true
{% endmacro %}


{# The output columns of one measure: <measure>_<statistic>. #}
{% macro form_stats_select(measure, n, decimals) %}
{%- for d in form_stat_definitions(n, decimals) %}
    {{ measure }}_s.{{ d.name }} as {{ measure }}_{{ d.name }}{{ ',' if not loop.last }}
{%- endfor %}
{% endmacro %}
