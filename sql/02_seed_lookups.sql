-- 02_seed_lookups.sql
-- The rows for the three lookup tables created in 01_schema.sql.
-- Safe to run more than once: ON CONFLICT DO NOTHING skips rows that exist.
--
-- Add a new row here whenever run_checks.py or a quarantine review shows
-- one is needed, then commit it, so a rebuilt database matches production.

-- API team ids shared by different clubs: (api_team_id, league_id) -> club_id.
-- club_id values start at 9000001 so they can never collide with an API id.
INSERT INTO basketball.club_id_overrides
    (api_team_id, league_id, club_id, club_name, note)
VALUES
    (239915, 16102,  9000001, 'Atenas (Argentina)',          'Liga A'),
    (239915, 94394,  9000002, 'Atenas (Uruguay)',            'Liga Uruguaya'),
    (352247, 76523,  9000003, 'Gorica (Slovenia)',           'Liga Nova KBM'),
    (352247, 139497, 9000003, 'Gorica (Slovenia)',           'Slovenian Cup'),
    (352247, 193961, 9000004, 'Gorica (Croatia)',            'Prva Liga'),
    (816893, 104606, 9000005, 'Al Ahli (Bahrain)',           'Premier League'),
    (816893, 66311,  9000006, 'Al Ahli (Qatar)',             'QBL'),
    (709667, 324164, 9000007, 'Soles (Dominican Republic)',  'LNB'),
    (709667, 54397,  9000008, 'Soles (Mexico)',              'LNBP'),
    (707114, 54397,  9000009, 'Panteras de Aguascalientes',  'Mexico LNBP; shares API id 707114 with the Venezuelan club'),
    (707114, 234809, 9000010, 'Panteras de Miranda',         'Venezuela Superliga; shares API id 707114 with the Mexican club')
ON CONFLICT (api_team_id, league_id) DO NOTHING;

-- Leagues that report two halves instead of four quarters.
INSERT INTO basketball.half_style_leagues (league_id, league_name, note)
VALUES
    (99500,  'NCAA', 'College basketball: two halves, reported in q2 and q4'),
    (152262, 'BIG3', '3-on-3 league: two halves, reported in q2 and q4'),
    (12698,  'NIT',  'USA college tournament; halves are stored in q2 and q4, with q1 and q3 as 0 - 0')
ON CONFLICT (league_id) DO NOTHING;

-- Leagues with invited clubs from other countries.
INSERT INTO basketball.international_leagues (league_id, league_name, note)
VALUES
    (225448, 'VTB Super Cup',      'Hosted in Russia, includes invited clubs from other countries (e.g. Anadolu Efes)'),
    (365863, 'WINLINE Basket Cup', 'Hosted in Russia, includes invited clubs from other countries (e.g. FMP Beograd)')
ON CONFLICT (league_id) DO NOTHING;