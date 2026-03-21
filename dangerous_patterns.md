# 危険箇所 (Pandas 直接真偽値評価の疑い)

| File | Line | Content | Description |
| --- | --- | --- | --- |
| calculator.py | 898 | `if odds_list:` | 直接判定 (if/while) -> odds_list |
| calculator.py | 1140 | `if results:` | 直接判定 (if/while) -> results |
| odds_logger.py | 211 | `if data:` | 直接判定 (if/while) -> data |
| odds_logger.py | 129 | `if not odds_data:` | 否定判定 (not) -> odds_data |
| odds_logger.py | 183 | `if not odds_list:` | 否定判定 (not) -> odds_list |
| odds_tracker.py | 102 | `if odds_data:` | 直接判定 (if/while) -> odds_data |
| odds_tracker.py | 118 | `if not results:` | 否定判定 (not) -> results |
| odds_tracker.py | 189 | `if raw_data:` | 直接判定 (if/while) -> raw_data |
| odds_tracker.py | 176 | `if win_odds:` | 直接判定 (if/while) -> win_odds |
| scraper.py | 430 | `if not results:` | 否定判定 (not) -> results |
| scraper.py | 741 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 1120 | `if trainer_a:` | 直接判定 (if/while) -> trainer_a |
| scraper.py | 1127 | `if not trainer:` | 否定判定 (not) -> trainer |
| scraper.py | 1129 | `if not trainer:` | 否定判定 (not) -> trainer |
| scraper.py | 535 | `if not results:` | 否定判定 (not) -> results |
| scraper.py | 576 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 621 | `if db_odds:` | 直接判定 (if/while) -> db_odds |
| scraper.py | 1237 | `if data01:` | 直接判定 (if/while) -> data01 |
| scraper.py | 1559 | `if missing_odds:` | 直接判定 (if/while) -> missing_odds |
| scraper.py | 578 | `if results:` | 直接判定 (if/while) -> results |
| scraper.py | 1406 | `if odds_td and h_data['Odds'] == 0.0:` | 論理演算判定 (and/or) -> odds_td |
| scraper.py | 1551 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 1562 | `if res_odds:` | 直接判定 (if/while) -> res_odds |
| scraper.py | 593 | `if results:` | 直接判定 (if/while) -> results |
| scraper.py | 884 | `rank = int(m_rank.group(1)) if m_rank else 99` | 三項演算判定 -> m_rank |
| scraper.py | 1409 | `if m_odds: h_data['Odds'] = float(m_odds.group(1))` | 直接判定 (if/while) -> m_odds |
| scraper.py | 272 | `if odds_el:` | 直接判定 (if/while) -> odds_el |
| scraper.py | 1430 | `if rank_span: run['Rank'] = int(rank_span.text.strip())` | 直接判定 (if/while) -> rank_span |
| theory_rmhs.py | 200 | `if 'Margin' in run_data and run_data['Margin']:` | 論理演算判定 (and/or) -> run_data['Margin'] |
| odds_tracker.py | 36 | `if data:` | 直接判定 (if/while) -> data |
| race_position_scanner.py | 281 | `if match_jockey or match_trainer:` | 論理演算判定 (and/or) -> match_jockey |
| race_position_scanner.py | 281 | `if match_jockey or match_trainer:` | 論理演算判定 (and/or) -> match_trainer |
| race_position_scanner.py | 283 | `if match_jockey:` | 直接判定 (if/while) -> match_jockey |
| race_position_scanner.py | 285 | `if match_trainer:` | 直接判定 (if/while) -> match_trainer |
| scrapling_jra.py | 33 | `if not results:` | 否定判定 (not) -> results |
| test_odds_fetcher.py | 17 | `if data:` | 直接判定 (if/while) -> data |
| app.py | 5359 | `if dates_with_data:` | 直接判定 (if/while) -> dates_with_data |
| app.py | 3661 | `if _pop_missing_t or _odds_missing_t:` | 論理演算判定 (and/or) -> _odds_missing_t |
| app.py | 4220 | `if _tsof_result["bets"]:` | 直接判定 (if/while) -> _tsof_result['bets'] |
| app.py | 4526 | `if results:` | 直接判定 (if/while) -> results |
| app.py | 1183 | `if _pop_missing or _odds_missing:` | 論理演算判定 (and/or) -> _odds_missing |
| app.py | 3014 | `if race_results:` | 直接判定 (if/while) -> race_results |
| app.py | 3070 | `if race_results:` | 直接判定 (if/while) -> race_results |
| app.py | 3249 | `if race_results:` | 直接判定 (if/while) -> race_results |
| app.py | 3265 | `if race_results:` | 直接判定 (if/while) -> race_results |
| app.py | 2408 | `if _san_result["bets"]:` | 直接判定 (if/while) -> _san_result['bets'] |
| app.py | 2464 | `if _sof_result["bets"]:` | 直接判定 (if/while) -> _sof_result['bets'] |
| app.py | 3180 | `if 'ActualRank' in disp_view.columns and race_results:` | 論理演算判定 (and/or) -> race_results |
| app.py | 1328 | `if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":` | 論理演算判定 (and/or) -> current_jockey |
| app.py | 1328 | `if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":` | 論理演算判定 (and/or) -> prev_jockey |
| app.py | 2128 | `if odds_list:` | 直接判定 (if/while) -> odds_list |
| app.py | 2144 | `if not odds_list:` | 否定判定 (not) -> odds_list |
| debug_odds.py | 31 | `if span_odds:` | 直接判定 (if/while) -> span_odds |
| test_app.py | 52 | `if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":` | 論理演算判定 (and/or) -> current_jockey |
| test_app.py | 52 | `if current_jockey and prev_jockey and current_jockey != prev_jockey and prev_jockey != "-":` | 論理演算判定 (and/or) -> prev_jockey |
| verify_evidence.py | 80 | `if invalid_trainers:` | 直接判定 (if/while) -> invalid_trainers |
| verify_evidence.py | 36 | `jockey=str(jockey), trainer=str(trainer) if trainer else None,` | 三項演算判定 -> trainer |
| calculator.py | 898 | `if odds_list:` | 直接判定 (if/while) -> odds_list |
| calculator.py | 1140 | `if results:` | 直接判定 (if/while) -> results |
| odds_logger.py | 211 | `if data:` | 直接判定 (if/while) -> data |
| odds_logger.py | 129 | `if not odds_data:` | 否定判定 (not) -> odds_data |
| odds_logger.py | 183 | `if not odds_list:` | 否定判定 (not) -> odds_list |
| odds_tracker.py | 102 | `if odds_data:` | 直接判定 (if/while) -> odds_data |
| odds_tracker.py | 118 | `if not results:` | 否定判定 (not) -> results |
| odds_tracker.py | 189 | `if raw_data:` | 直接判定 (if/while) -> raw_data |
| odds_tracker.py | 176 | `if win_odds:` | 直接判定 (if/while) -> win_odds |
| scraper.py | 430 | `if not results:` | 否定判定 (not) -> results |
| scraper.py | 741 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 1120 | `if trainer_a:` | 直接判定 (if/while) -> trainer_a |
| scraper.py | 1127 | `if not trainer:` | 否定判定 (not) -> trainer |
| scraper.py | 1129 | `if not trainer:` | 否定判定 (not) -> trainer |
| scraper.py | 535 | `if not results:` | 否定判定 (not) -> results |
| scraper.py | 576 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 621 | `if db_odds:` | 直接判定 (if/while) -> db_odds |
| scraper.py | 1237 | `if data01:` | 直接判定 (if/while) -> data01 |
| scraper.py | 1559 | `if missing_odds:` | 直接判定 (if/while) -> missing_odds |
| scraper.py | 578 | `if results:` | 直接判定 (if/while) -> results |
| scraper.py | 1406 | `if odds_td and h_data['Odds'] == 0.0:` | 論理演算判定 (and/or) -> odds_td |
| scraper.py | 1551 | `if api_data:` | 直接判定 (if/while) -> api_data |
| scraper.py | 1562 | `if res_odds:` | 直接判定 (if/while) -> res_odds |
| scraper.py | 593 | `if results:` | 直接判定 (if/while) -> results |
| scraper.py | 884 | `rank = int(m_rank.group(1)) if m_rank else 99` | 三項演算判定 -> m_rank |
| scraper.py | 1409 | `if m_odds: h_data['Odds'] = float(m_odds.group(1))` | 直接判定 (if/while) -> m_odds |
| scraper.py | 272 | `if odds_el:` | 直接判定 (if/while) -> odds_el |
| scraper.py | 1430 | `if rank_span: run['Rank'] = int(rank_span.text.strip())` | 直接判定 (if/while) -> rank_span |
| theory_rmhs.py | 200 | `if 'Margin' in run_data and run_data['Margin']:` | 論理演算判定 (and/or) -> run_data['Margin'] |
| odds_tracker.py | 36 | `if data:` | 直接判定 (if/while) -> data |
| race_position_scanner.py | 281 | `if match_jockey or match_trainer:` | 論理演算判定 (and/or) -> match_jockey |
| race_position_scanner.py | 281 | `if match_jockey or match_trainer:` | 論理演算判定 (and/or) -> match_trainer |
| race_position_scanner.py | 283 | `if match_jockey:` | 直接判定 (if/while) -> match_jockey |
| race_position_scanner.py | 285 | `if match_trainer:` | 直接判定 (if/while) -> match_trainer |
| scrapling_jra.py | 33 | `if not results:` | 否定判定 (not) -> results |
| test_odds_fetcher.py | 17 | `if data:` | 直接判定 (if/while) -> data |
