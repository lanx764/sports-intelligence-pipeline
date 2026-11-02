-- 02_seed_lookups.sql
-- The rows for the lookup tables created in 01_schema.sql.
-- Safe to run more than once: ON CONFLICT DO NOTHING skips rows that exist.
--
-- Add a new row here whenever run_checks.py or a quarantine review shows
-- one is needed, then commit it, so a rebuilt database matches production.

-- API team ids shared by different clubs: (api_team_id, league_id) -> club_id.
-- club_id values start at 9000001 so they can never collide with an API id.
-- One club_id per real club, reused across that club's leagues. Before
-- inventing a new club_id, check the highest one in club_id_overrides AND
-- club_corrections (last used: 9000038).
-- Every league a shared id plays in needs its own row; a league that is
-- not listed is quarantined as "ambiguous club" until a row is added.
INSERT INTO basketball.club_id_overrides
    (api_team_id, league_id, club_id, club_name, note)
VALUES
    (239915, 16102,  9000001, 'Atenas (Argentina)',          'Liga A'),
    (239915, 94394,  9000002, 'Atenas (Uruguay)',            'Liga Uruguaya'),
    (352247, 76523,  9000003, 'Gorica (Slovenia)',           'Liga Nova KBM'),
    (352247, 139497, 9000003, 'Gorica (Slovenia)',           'Slovenian Cup'),
    (352247, 193961, 9000004, 'Gorica (Croatia)',            'Prva Liga'),
    (352247, 108010, 9000004, 'Gorica (Croatia)',            'Croatian Cup'),
    (352247, 26314, 9000004, 'Gorica (Croatia)', 'Premijer liga; Alkar - Gorica 102-109 (2023-04-22) confirmed on Flashscore'),
    (816893, 104606, 9000005, 'Al Ahli (Bahrain)',           'Premier League'),
    (816893, 66311,  9000006, 'Al Ahli (Qatar)',             'QBL'),
    (816893, 72268,  9000011, 'Al Ahli (Saudi Arabia)',      'Saudi Premier League'),
    (709667, 324164, 9000007, 'Soles (Dominican Republic)',  'LNB'),
    (709667, 54397,  9000008, 'Soles (Mexico)',              'LNBP'),
    (707114, 54397,  9000009, 'Panteras de Aguascalientes',  'Mexico LNBP; shares API id 707114 with the Venezuelan club'),
    (707114, 234809, 9000010, 'Panteras de Miranda',         'Venezuela Superliga; shares API id 707114 with the Mexican club'),
    (174388, 82480,  9000012, 'Toledo (Spain)',              'LEB Plata; the API lists this club as "Toledo Rockets", same name and id as the US college'),
    (174388, 99500,  9000013, 'Toledo Rockets (USA)',        'NCAA'),
    (888377, 72268,  9000014, 'Al Ittihad (Saudi Arabia)',   'Saudi Premier League; also the Jeddah club in WASL (331823), where API id 888377 is shared with Al Ittihad Aleppo, so WASL games are set per game in club_corrections'),
    (888377, 104606, 9000015, 'Al Ittihad (Bahrain)',        'Premier League'),
    (109712, 9294,   9000016, 'LDLC ASVEL Women (France)',   'French League Women'),
    (109712, 197365, 9000016, 'LDLC ASVEL Women (France)',   'Coupe de France Women'),
    (109712, 306293, 9000016, 'LDLC ASVEL Women (France)', 'EuroLeague Women; FIBA EuroLeague Women 2023-24 roster lists LDLC ASVEL Feminin with all opponents in these games'),
    (109712, 307144, 9000016, 'LDLC ASVEL Women (France)', 'EuroCup Women; same team name and only European women''s club opponents; no independent source yet'),
    (109712, 335227, 9000016, 'LDLC ASVEL Women (France)', 'LFB Super Cup Women; opponent Landes (French club); no independent source yet'),
    (109712, 307995, 9000016, 'LDLC ASVEL Women (France)', 'SuperCup Women; opponent Fenerbahce; no independent source yet'),
    (109712, 360757, 9000017, 'Lyon College (USA)',          'NCAA Women; the API labels Lyon College as LDLC ASVEL Women (Central Arkansas 115-43 Lyon, 2025-11-07)'),
    (610951, 45036,  9000018, 'Brescia (Italy)',             'Lega A'),
    (610951, 165878, 9000018, 'Brescia (Italy)', 'EuroCup Basketball; Turk Telekom 77-69 Brescia (2023-04-13) matches Wikipedia 2022-23 EuroCup eighthfinals; source date there is 12 April'),
    (610951, 121626, 9000018, 'Brescia (Italy)',             'Lega A - Super Cup'),
    (610951, 122477, 9000018, 'Brescia (Italy)',             'Coppa Italia'),
    (610951, 99500,  9000019, 'Brescia University (USA)',    'NCAA; small US college, not the Italian club'),
    (2281464, 84182, 9000020, 'Viby (Sweden)',               'Basketettan Women; shares API id 2281464 with the Danish Viby'),
    (1399828, 65460,  9000021, 'Cangrejeros (Puerto Rico)', 'BSN; likely Cangrejeros de Santurce; shares API id 1399828 with the Venezuelan club'),
    (1399828, 234809, 9000022, 'Cangrejeros (Venezuela)',   'Superliga; likely Cangrejeros de Monagas; shares API id 1399828 with the Puerto Rican club'),
    (250127,  16102,  9000023, 'Penarol (Argentina)',       'Liga A; shares API id 250127 with the Uruguayan club'),
    (250127,  94394,  9000024, 'Penarol (Uruguay)',         'Liga Uruguaya; shares API id 250127 with the Argentine club'),
    (250127,  353098, 9000024, 'Penarol (Uruguay)',         'Liga Sudamericana; the 5 games (Oct-Dec 2023) match reports on the Uruguayan Penarol'),
    (1205800, 10996, 9000025, 'East (NBA All-Star)',        'NBA All-Star Game; API reuses id 1205800 for East in other leagues'),
    (1205800, 28016, 9000026, 'East (Czech NBL All-Star)',  'Czech NBL All-Star Game; API reuses id 1205800 for East in other leagues'),
    (1206651, 10996, 9000027, 'West (NBA All-Star)',        'NBA All-Star Game; API reuses id 1206651 for West in other leagues'),
    (1206651, 28016, 9000028, 'West (Czech NBL All-Star)',  'Czech NBL All-Star Game; API reuses id 1206651 for West in other leagues'),
    (321611,  8443,   9000029, 'Laval (France)',               'Coupe de France; French club Union Sportive Lavalloise, shares API id 321611 with the Canadian Universite Laval'),
    (2281464, 111414, 9000030, 'Viby (Denmark)',               'Danish Cup Women; Danish club, shares API id 2281464 with the Swedish Viby in Basketettan'),
    (316505,  99500,  9000031, 'Concordia Ann Arbor (USA)',    'NCAA; US college, shares API id 316505 with the Canadian Concordia'),
    (470536,  99500,  9000032, 'Heidelberg University (USA)',  'NCAA; Ohio college (Student Princes), shares API id 470536 with the German club USC Heidelberg'),
    (347992,  99500,  9000033, 'York University Nebraska (USA)', 'NCAA; US college, shares API id 347992 with the Canadian York. The 2024-11-05 game was reported as the Nebraska college by one source and only partly confirmed'),
    (321611,  25463,  9000034, 'Laval (Canada)',               'U SPORTS; Universite Laval, shares API id 321611 with the French club'),
    (316505,  25463,  9000035, 'Concordia (Canada)',           'U SPORTS; shares API id 316505 with the US college Concordia Ann Arbor'),
    (347992,  25463,  9000036, 'York (Canada)',                'U SPORTS; shares API id 347992 with the US college York University Nebraska'),
    (470536,  34824,  9000037, 'USC Heidelberg (Germany)',     'BBL; shares API id 470536 with the US college Heidelberg University'),
    (470536,  36526,  9000037, 'USC Heidelberg (Germany)',     'Pro A'),
    (470536,  114818, 9000037, 'USC Heidelberg (Germany)',     'German Cup'),
    (470536,  172686, 9000037, 'USC Heidelberg (Germany)',     'Champions League')
ON CONFLICT (api_team_id, league_id) DO NOTHING;

-- One side of one game is a specific club: for an API team id used by two
-- different clubs inside the same league. api_team_id is the id expected on
-- that side. Club 9000038 (Al Ittihad Aleppo) exists only here, not in
-- club_id_overrides.
-- API id 888377 in WASL (league 331823): Al Ittihad Aleppo (Syria) played the
-- West Asia League in 2023-24; Ittihad Club of Jeddah (Saudi Arabia) played
-- the Gulf League and Final 8 from 2024-25. Sources: FIBA team profiles.
INSERT INTO basketball.club_corrections
    (match_id, side, api_team_id, club_id, club_name, note)
VALUES
    (315122680, 'home', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Naft Al Janoob'),
    (315129488, 'away', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Shahrdari Gorgan'),
    (315136296, 'home', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Sagesse Beirut'),
    (315143104, 'away', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Naft Al Janoob'),
    (315149061, 'home', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Shahrdari Gorgan'),
    (315156720, 'away', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Sagesse Beirut'),
    (331297637, 'away', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24 qualification; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Al-Shorta'),
    (331299339, 'home', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24 qualification; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Al-Shorta'),
    (332809864, 'away', 888377, 9000038, 'Al Ittihad Aleppo (Syria)', 'WASL West Asia League 2023-24 qualification; FIBA lists Al-Ittihad Ahli of Aleppo, Syria in the West Asia League; opponent Al-Shorta'),
    (362443386, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2024-25; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al Arabi'),
    (362445939, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2024-25; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al Qadsia'),
    (381727897, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2025; FIBA: Al Ittihad, Saudi giants from Jeddah; opponent Sagesse Beirut'),
    (381730450, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2025; FIBA: Al Ittihad, Saudi giants from Jeddah; opponent Astana'),
    (381734705, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2025; FIBA: Al Ittihad, Saudi giants from Jeddah; opponent Al-Riyadi'),
    (402267633, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al Shabab'),
    (402271037, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Kazma SC'),
    (402276143, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al-Muharraq'),
    (402282951, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al Shabab'),
    (402289759, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Kazma SC'),
    (402297418, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Gulf League 2025-26; FIBA Ittihad Club, Saudi side from Jeddah; opponent Al-Muharraq'),
    (443115633, 'home', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2026; FIBA headlines Kuwait Club repel Ittihad Club; headlines only, full articles not read; opponent Kuwait SC'),
    (443119037, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2026; FIBA Ittihad Club in the Final 8; headlines only, full articles not read; opponent Indian Railways'),
    (443123292, 'away', 888377, 9000014, 'Al Ittihad (Saudi Arabia)', 'WASL Final 8 2026; FIBA Ittihad Club in the Final 8; headlines only, full articles not read; opponent Al-Riyadi')
ON CONFLICT (match_id, side) DO NOTHING;

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

INSERT INTO basketball.league_corrections
    (match_id, league_id, league, country, reason)
VALUES
    (329942845, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306536941, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306537792, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306539494, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306546302, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (329943696, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306541196, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306542047, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306542898, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306543749, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306544600, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306540345, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306547153, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306548855, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306549706, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (327000087, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306538643, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306550557, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306551408, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306552259, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306553110, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306553961, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (306548004, 93543, 'WBBL Women', 'United Kingdom', 'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research'),
    (332945173, 53546, 'Moteru Lyga Women', 'Lithuania', 'API filed this game under Greece Basket League (39079); true league confirmed by manual research')
ON CONFLICT (match_id) DO NOTHING;