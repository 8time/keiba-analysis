import PIL.Image
import numpy as np
import io
import pandas as pd
import logging
import re

logger = logging.getLogger(__name__)

class LocalVisionOddsAnalyzer:
    def __init__(self, languages=['ja', 'en']):
        self.init_error = None
        self.languages = languages
        self.reader = None
        try:
            import easyocr
            self.reader = easyocr.Reader(self.languages, gpu=False)
            logger.info("EasyOCR Reader initialized successfully (GPU=False).")
        except ImportError as e:
            self.init_error = "EasyOCR ライブラリがインストールされていません。pip install easyocr を確認してください。"
            logger.error(self.init_error)
        except Exception as e:
            self.init_error = str(e)
            logger.error(f"Failed to initialize EasyOCR: {self.init_error}")
            self.reader = None

    def analyze_odds_image(self, image_bytes: bytes):
        debug_info = []
        if self.reader is None:
            return None, f"EasyOCR の初期化に失敗しました。原因: {self.init_error if self.init_error else 'ライブラリ未検出'}", []
        try:
            image_np = np.array(PIL.Image.open(io.BytesIO(image_bytes)))
            results = self.reader.readtext(image_np)
            if not results:
                return None, "画像からテキストを検出できませんでした。", []
            data, debug_info = self._parse_ocr_results(results)
            if not data:
                return None, "テキストは検出されましたが、期待される表形式（馬番・オッズ等）を特定できませんでした。", debug_info
            logger.info(f"Local OCR extracted {len(data)} horses from image.")
            return data, None, debug_info
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Local OCR analysis failed: {err_msg}")
            return None, f"解析中にエラーが発生しました: {err_msg}", debug_info

    def _parse_ocr_results(self, results):
        items = []
        img_x_max = 0

        for bbox, text, conf in results:
            y_min = min(p[1] for p in bbox)
            y_max = max(p[1] for p in bbox)
            x_left = min(p[0] for p in bbox)
            x_right = max(p[0] for p in bbox)
            img_x_max = max(img_x_max, x_right)

            clean_text = text.strip()
            num_text = clean_text.replace(",", ".").replace(" ", "").replace(":", ".")
            if num_text in ["I", "|", "l", "]", "J", "i"]:
                num_text = "1"

            items.append({
                'y': (y_min + y_max) / 2,
                'x': x_left,
                'x_center': (x_left + x_right) / 2,
                'x_max': x_right,
                'text': clean_text,
                'num_text': num_text,
                'h': (y_max - y_min)
            })

        if not items:
            return [], []

        items.sort(key=lambda x: x['y'])

        # 行グルーピング
        rows = []
        current_row = [items[0]]
        for i in range(1, len(items)):
            threshold = max(items[i]['h'], current_row[-1]['h']) * 0.4
            if abs(items[i]['y'] - current_row[-1]['y']) < threshold:
                current_row.append(items[i])
            else:
                rows.append(current_row)
                current_row = [items[i]]
        rows.append(current_row)

        if img_x_max == 0:
            img_x_max = max(item['x_max'] for item in items)

        debug_lines = []

        # --- ヘッダー行から列X座標を特定 ---
        # 「オッズ」単体のセル（「オッズ・購入」タブではなく列ヘッダー）を探す
        # 条件: 'オッズ'を含み、かつその行に'人気'も含まれる行
        odds_x_center = None
        popularity_x_center = None
        umaban_x_center = None

        for row in rows:
            row_text = " ".join([item['text'] for item in row])
            # 列ヘッダー行: 馬名・オッズ・人気が同じ行にある
            if 'オッズ' in row_text and '人気' in row_text and '馬名' in row_text:
                for item in row:
                    t = item['text']
                    if t == 'オッズ' or t == 'オッズ ':
                        odds_x_center = item['x_center']
                    elif 'オッズ' in t and '人気' not in t and odds_x_center is None:
                        # "オッズ"を含む最右のアイテム
                        pass
                    if '人気' in t:
                        popularity_x_center = item['x_center']
                    if '馬番' in t or t in ['枠', '枠番']:
                        umaban_x_center = item['x_center']

                # オッズが単体で見つからなかった場合、行内で最も右の「オッズ」含むアイテム
                if odds_x_center is None:
                    odds_items = [item for item in row if 'オッズ' in item['text']]
                    if odds_items:
                        # 一番右のものを採用（タブメニューではなく列ヘッダー）
                        odds_x_center = max(odds_items, key=lambda x: x['x_center'])['x_center']

                debug_lines.append(f"[列ヘッダー検出] 馬番X:{umaban_x_center} オッズX:{odds_x_center} 人気X:{popularity_x_center}")
                break

        # フォールバック: ヘッダーなしの場合、右側の小数値の集中帯を使用
        if odds_x_center is None:
            float_xs = []
            for row in rows:
                for item in row:
                    t = item['num_text']
                    if re.match(r'^\d+\.\d+$', t):
                        val = float(t)
                        # オッズらしい範囲（1.0〜999.9）かつ画像右寄り
                        if 1.0 <= val <= 999.9 and item['x_center'] > img_x_max * 0.55:
                            float_xs.append(item['x_center'])
            if float_xs:
                odds_x_center = float(np.median(float_xs))
                debug_lines.append(f"[統計推定] オッズX:{odds_x_center:.0f}")

        if popularity_x_center is None and odds_x_center is not None:
            int_xs = []
            for row in rows:
                for item in row:
                    t = item['num_text']
                    if re.match(r'^\d+$', t) and 1 <= int(t) <= 18 and item['x_center'] > odds_x_center:
                        int_xs.append(item['x_center'])
            if int_xs:
                popularity_x_center = float(np.median(int_xs))
                debug_lines.append(f"[統計推定] 人気X:{popularity_x_center:.0f}")

        col_tol = img_x_max * 0.06
        debug_lines.append(f"[設定] 画像幅:{img_x_max:.0f} オッズX:{odds_x_center} 人気X:{popularity_x_center} 許容:±{col_tol:.0f}")

        # スキップキーワード（ヘッダー・フッター・メニュー行）
        skip_kw = ['オッズ', '人気', '馬名', '出走馬', '競馬新聞', '出馬表', '選んだ馬',
                   'コース', 'PAT', '発走', '本賞金', '調教', '結果', 'レース',
                   '掲示板', 'データ', '専門紙', 'タイム', 'バドック', '血統',
                   '馬メモ', '登録', 'グループ', '切替', '馬場', '回京', '回阪',
                   '回中', '回東', '回小', '回福', '回札']

        parsed_data = []
        horse_order = 0

        for row in rows:
            row.sort(key=lambda x: x['x'])
            row_text_combined = " ".join([item['text'] for item in row])
            full_text_row = " | ".join([f"{item['text']}(x:{int(item['x_center'])})" for item in row])

            if any(kw in row_text_combined for kw in skip_kw):
                continue

            # Determine row-wide attributes
            SEX_NORM = {'壮': '牡', '北': '牡', 'プ': '牝', '#': '牡', '廿': '牡', '幸': '牝'}
            row_sex_age = None
            row_weight = None
            row_umaban = None
            
            for item in row:
                t_raw = item['text']
                t_num = item['num_text'].replace(",", ".")
                
                # Sex/Age
                norm_sex = t_raw
                for k, v in SEX_NORM.items(): norm_sex = norm_sex.replace(k, v)
                m_sex = re.search(r'([牡牝セ])(\d+)', norm_sex)
                if m_sex and not row_sex_age:
                    row_sex_age = m_sex.group(0)
                
                # Weight (斤量)
                if not row_weight:
                    m_futan = re.search(r'^(\d{2}\.\d)$', t_num)
                    if m_futan:
                        try:
                            fv = float(m_futan.group(1))
                            if 40.0 <= fv <= 70.0: row_weight = f"{fv:.1f}"
                        except: pass
                
                # Umaban (Leftmost 1-18)
                if not row_umaban:
                    if re.match(r'^\d+$', t_num) and 1 <= int(t_num) <= 18:
                        if odds_x_center is None or item['x_center'] < odds_x_center * 0.7:
                            row_umaban = int(t_num)

            # --- Target Win Odds & Popularity for this ROW ---
            found_odds_val = None
            found_pop_val = None
            best_odds_dist = float('inf')

            for i, item in enumerate(row):
                t_num = item['num_text'].replace(",", ".")
                
                # Odds Candidate
                if re.match(r'^\d+\.\d+$', t_num):
                    val = float(t_num)
                    if 1.0 <= val <= 999.9:
                        # Check distance to odds_x_center
                        if odds_x_center is not None:
                            dist = abs(item['x_center'] - odds_x_center)
                        else:
                            # Fallback: Prefer right side
                            dist = abs(item['x_center'] - img_x_max * 0.7)
                        
                        # Only take the one closest to our expected column
                        if dist < best_odds_dist:
                            best_odds_dist = dist
                            found_odds_val = val
                            
                            # Peek next for popularity
                            if i + 1 < len(row):
                                next_item = row[i+1]
                                nt_num = next_item['num_text'].replace(",", ".")
                                if re.match(r'^\d+$', nt_num):
                                    iv = int(nt_num)
                                    if 1 <= iv <= 18:
                                        found_pop_val = iv

            if found_odds_val is None:
                continue

            # Umaban backup
            if not row_umaban:
                # If we have a sequence but no umaban found, use order
                horse_order += 1
                row_umaban = horse_order
            
            # --- CRITICAL BUG FIX: Limit to 18 horses and ensure validity ---
            if row_umaban > 18 or found_odds_val is None:
                continue

            rd = {
                "umaban": row_umaban,
                "popularity": found_pop_val,
                "win_odds": found_odds_val,
                "sex_age": row_sex_age,
                "weight_carried": row_weight,
                "place_min": None, "place_max": None
            }
            
            # Place Odds (Min-Max)
            for item in row:
                pr = re.findall(r"(\d+\.\d+)[\-\~](\d+\.\d+)", item['num_text'].replace(",", "."))
                if pr:
                    rd["place_min"] = float(pr[0][0])
                    rd["place_max"] = float(pr[0][1])
                    break

            # Deduplicate by Umaban
            if not any(d['umaban'] == rd['umaban'] for d in parsed_data):
                debug_lines.append(f"  [Row Fixed] Umaban:{rd['umaban']} Odds:{rd['win_odds']} Pop:{rd['popularity']}")
                parsed_data.append(rd)

        parsed_data.sort(key=lambda x: x['umaban'])
        return parsed_data, debug_lines

    def merge_vision_data(self, df, vision_data):
        if not vision_data or df.empty:
            return df
        v_df = pd.DataFrame(vision_data)
        v_df = v_df.rename(columns={
            "umaban": "Umaban",
            "popularity": "Popularity",
            "win_odds": "Odds",
            "place_min": "Show Odds (Min)",
            "place_max": "Show Odds (Max)",
            "sex_age": "SexAge",
            "weight_carried": "WeightCarried"
        })
        try:
            df['Umaban'] = pd.to_numeric(df['Umaban'], errors='coerce')
            v_df['Umaban'] = pd.to_numeric(v_df['Umaban'], errors='coerce')
            v_df_valid = v_df.dropna(subset=['Umaban'])
            for _, row in v_df_valid.iterrows():
                umaban_val = int(row['Umaban'])
                idx = df[df['Umaban'] == umaban_val].index
                if not idx.empty:
                    i = idx[0]
                    if pd.notna(row.get('Odds')): df.at[i, 'Odds'] = row['Odds']
                    if pd.notna(row.get('Popularity')): df.at[i, 'Popularity'] = row['Popularity']
                    if pd.notna(row.get('Show Odds (Min)')): df.at[i, 'Show Odds (Min)'] = row['Show Odds (Min)']
                    if pd.notna(row.get('Show Odds (Max)')): df.at[i, 'Show Odds (Max)'] = row['Show Odds (Max)']
                    if pd.notna(row.get('SexAge')): df.at[i, 'SexAge'] = row['SexAge']
                    if pd.notna(row.get('WeightCarried')): df.at[i, 'WeightCarried'] = row['WeightCarried']
                    logger.info(f"Updated Umaban {umaban_val} with Vision data (incl. Sex/Weight).")
        except Exception as e:
            logger.error(f"Error during vision data merge: {e}")
        return df

