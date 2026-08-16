# -*- coding: utf-8 -*-
"""core/batch_analyze.py — 日付指定バッチ解析(Streamlit非依存)。

指定日のレースを実際に動いている `streamlit run app.py` に対して
Playwrightでブラウザ自動化し、🏠Single Race Analysis / 🧹消去フィルターの
既存UIコードパスをそのまま走らせて data/newspaper/{race_id}.*.json の
スナップショットを生成する。

SRAブロック(app.py)は100件超の検証済みエッジがStreamlit UIと密結合しており、
これをPythonロジックとして移植するとフィデリティが保証できない
(移植ミスが新聞の内容を黙って古く/間違ったものにする事故に直結する)。
そのため移植ではなく、実際のアプリを操作する方式を採る。

重要な既知の挙動: app.py の🏠SRAページは 'persisted_main_race_id' を
session_stateに永続化するため、同一ブラウザセッション(同一タブでの
goto連打)で2レース目を開いてもURLのrace_idクエリパラメータが無視される
(直前のレースIDのまま解析されてしまう)。そのため1レースにつき
Playwrightの BrowserContext を新規作成し、使用後は必ず閉じる。
"""
import glob
import json
import os
import re
import sys
import time

from core import newspaper as _np
from core import scraper as _scraper

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ISSUES_DIR = os.path.join(ROOT, 'data', 'newspaper_issues')
PREFS_PATH = os.path.join(ROOT, 'user_prefs.json')

SRA_NAV = '🏠 Single Race Analysis'
ELIM_NAV = '🧹 消去フィルター'
ELIM_RACE_ID_LABEL = "netkeibaのレースIDを入力して Enter（URL貼り付けでもOK・出馬表を自動取得）"
ELIM_RUN_BUTTON = "▶ 強適消去エンジンを実行"


def fetch_day_race_ids(date_str, venues=None):
    """指定日(YYYYMMDD)のレース一覧を返す。JRA/NAR自動判別込み。

    venues: 指定時はvenue名の部分一致でフィルタ(例: ['東京','中山'])。
    戻り値: [{'race_id','race_num','race_name','venue'}, ...]
    """
    rows = _scraper.get_race_list_for_date(date_str) or []
    if venues:
        _vset = set(venues)
        rows = [r for r in rows if r.get('venue') in _vset]
    return rows


def check_streamlit_alive(base_url):
    """Streamlitサーバが応答するか確認。"""
    import requests
    for path in ('/_stcore/health', '/'):
        try:
            resp = requests.get(base_url.rstrip('/') + path, timeout=5)
            if resp.status_code == 200:
                return True
        except Exception:
            continue
    return False


def _snapshot_mtimes(race_id):
    """data/newspaper/{race_id}.*.json のファイル名→mtime辞書。"""
    pattern = os.path.join(_np.NP_DIR, f"{race_id}.*.json")
    out = {}
    for path in glob.glob(pattern):
        try:
            out[os.path.basename(path)] = os.path.getmtime(path)
        except OSError:
            continue
    return out


def _wait_for_quiet(race_id, baseline, required_substr=None, quiet_s=4, timeout_s=180, poll_s=1.0):
    """view.json(等)の更新が止まるまで待つ。

    required_substr: このsubstringを含むファイル名が新規/更新されるまでは
    「完了」と判定しない(例: 'view' や 'elim_verdict')。Noneなら任意の更新で可。
    戻り値: (完了したか, 最終スナップショット)
    """
    start = time.time()
    prev_snap = dict(baseline)   # 直前ポーリング時点のスナップショット(毎回更新)
    last_change = start
    last_snap = dict(baseline)
    satisfied = required_substr is None
    while True:
        now = time.time()
        snap = _snapshot_mtimes(race_id)
        changed = False
        for fname, mtime in snap.items():
            # 直前ポーリングとの差分でのみ「変化」を判定する。固定の初回baselineと
            # 比較し続けると、一度でも更新されたファイルが永遠に「変化あり」扱いになり
            # quiet(沈静化)条件に到達できなくなるバグがあったため、prev_snapを都度更新する。
            if prev_snap.get(fname) != mtime:
                changed = True
                if required_substr and required_substr in fname:
                    satisfied = True
        if changed:
            last_change = now
            last_snap = snap
        prev_snap = snap
        if satisfied and (now - last_change) >= quiet_s:
            return True, last_snap
        if (now - start) >= timeout_s:
            return False, last_snap
        time.sleep(poll_s)


SIGNAL_SCAN_BUTTON = "🔬 当日シグナルスキャン"


def run_sra_for_race(browser, base_url, race_id, timeout_s=180, with_signal=True):
    """SRAページを新規BrowserContextで開き、view.jsonの更新完了を待つ。

    with_signal=True なら🔬当日シグナルスキャンのボタンが出ていれば押す。
    このスキャンは当日全レースを走査する重い処理だが、結果は日付キャッシュ
    (data/signal_cache)に落ちるので実際に走るのは その日の初回1回だけ。
    2レース目以降はボタン自体が出ない(スキャン済み表示になる)。
    """
    result = {'race_id': race_id, 'stage': 'sra', 'status': 'failed',
              'elapsed_s': 0.0, 'error': None, 'signal': ''}
    t0 = time.time()
    baseline = _snapshot_mtimes(race_id)
    context = None
    try:
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout_s * 1000)
        url = f"{base_url}/?nav={_np_quote(SRA_NAV)}&race_id={race_id}"
        page.goto(url, wait_until='networkidle', timeout=timeout_s * 1000)
        ok, _ = _wait_for_quiet(race_id, baseline, required_substr='view',
                                 timeout_s=timeout_s)
        if with_signal and ok:
            try:
                _btn = page.get_by_role('button', name=SIGNAL_SCAN_BUTTON)
                if _btn.count() > 0 and _btn.first.is_visible():
                    _base2 = _snapshot_mtimes(race_id)
                    _btn.first.click()
                    # 当日全レース走査なので通常より長く待つ
                    _sok, _ = _wait_for_quiet(race_id, _base2, required_substr='view',
                                              timeout_s=max(timeout_s, 600))
                    result['signal'] = 'scanned' if _sok else 'timeout'
                else:
                    result['signal'] = 'cached'
            except Exception as _se:
                result['signal'] = f'skip({type(_se).__name__})'
        result['status'] = 'ok' if ok else 'timeout'
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {e}"
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        result['elapsed_s'] = round(time.time() - t0, 1)
    return result


def run_elim_filter_for_race(browser, base_url, race_id, timeout_s=90):
    """消去フィルターページを新規BrowserContextで開き、
    ▶ 強適消去エンジンを実行 をクリックしてelim_verdict.jsonの完了を待つ。"""
    result = {'race_id': race_id, 'stage': 'elim', 'status': 'failed',
              'elapsed_s': 0.0, 'error': None}
    t0 = time.time()
    baseline = _snapshot_mtimes(race_id)
    context = None
    try:
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout_s * 1000)
        url = f"{base_url}/?nav={_np_quote(ELIM_NAV)}"
        page.goto(url, wait_until='networkidle', timeout=timeout_s * 1000)
        box = page.get_by_label(ELIM_RACE_ID_LABEL)
        box.fill(str(race_id))
        box.press('Enter')
        run_btn = page.get_by_role('button', name=ELIM_RUN_BUTTON)
        run_btn.wait_for(state='visible', timeout=timeout_s * 1000)
        # データ取得スピナーが終わりボタンが押せる状態になるまで少し待つ
        page.wait_for_timeout(1000)
        run_btn.click()
        ok, _ = _wait_for_quiet(race_id, baseline, required_substr='elimv',
                                 timeout_s=timeout_s)
        result['status'] = 'ok' if ok else 'timeout'
    except Exception as e:
        result['error'] = f"{type(e).__name__}: {e}"
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
        result['elapsed_s'] = round(time.time() - t0, 1)
    return result


def _np_quote(s):
    import urllib.parse
    return urllib.parse.quote(s)


def _view_has_odds(race_id):
    """view.json にオッズが1頭でも入っているか。

    オッズ発表前に解析したスナップショットは全馬 '-' で保存され、
    荒れ度・妙味度・EVが出せない『中身の薄い』紙面になる。
    ファイルの有無だけで解析済みと見なすとこれが永久に残るため、
    中身まで見て判定する。
    """
    try:
        v = _np.load_view(race_id)
    except Exception:
        return False
    for rec in ((v or {}).get('records') or []):
        raw = str(rec.get('Odds', '') or '')
        m = re.search(r'\d+(?:\.\d+)?', raw)
        if m and float(m.group()) > 0:
            return True
    return False


def _has_snapshots(race_id):
    # newspaper.py の実ファイル名規則(_view_path/_elim_verdict_path)をそのまま利用し、
    # 命名規約の食い違い(view.json/elimv.json)を作らない。
    # view はファイルがあってもオッズ未取得なら『未解析』扱いにして再解析させる。
    view_ok = (os.path.exists(_np._view_path(race_id))
               and _view_has_odds(race_id))
    elim_ok = os.path.exists(_np._elim_verdict_path(race_id))
    return view_ok, elim_ok


# ────────────────────────────────────────────────────────────
# 進捗ステータス(UI連携用)
#   バッチは30〜60分かかるためStreamlitのコールバック内で同期実行すると
#   ページが操作不能になる。さらにPlaywrightが同じStreamlitサーバへ
#   新セッションを開くため自己ブロックの危険もある。そこでバッチは
#   別プロセスで走らせ、進捗をこのJSONファイル経由でUIへ伝える。
# ────────────────────────────────────────────────────────────

STATUS_PATH = os.path.join(ISSUES_DIR, 'batch_status.json')


def read_status():
    """現在の進捗ステータスを読む(無ければNone)。"""
    try:
        with open(STATUS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def write_status(payload):
    try:
        os.makedirs(ISSUES_DIR, exist_ok=True)
        tmp = STATUS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
        os.replace(tmp, STATUS_PATH)   # 部分書き込みをUIに読ませない
    except Exception:
        pass


def clear_status():
    try:
        os.remove(STATUS_PATH)
    except Exception:
        pass


def pid_alive(pid):
    """プロセスが生きているか(Windows/POSIX両対応)。"""
    if not pid:
        return False
    try:
        import subprocess
        if os.name == 'nt':
            out = subprocess.run(['tasklist', '/FI', f'PID eq {int(pid)}'],
                                 capture_output=True, text=True, timeout=5)
            return str(pid) in (out.stdout or '')
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def is_running():
    """バッチが実行中か。ステータスがrunningでもプロセスが死んでいればFalse。"""
    st_ = read_status()
    if not st_ or st_.get('state') != 'running':
        return False
    return pid_alive(st_.get('pid'))


def stop_batch():
    """実行中バッチを停止する。停止できたらTrue。"""
    st_ = read_status()
    pid = (st_ or {}).get('pid')
    if not pid:
        return False
    try:
        import subprocess
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(int(pid))],
                           capture_output=True, timeout=10)
        else:
            import signal
            os.kill(int(pid), signal.SIGTERM)
    except Exception:
        return False
    if st_:
        st_['state'] = 'stopped'
        st_['updated_ts'] = time.time()
        write_status(st_)
    return True


def start_batch_subprocess(date_str=None, race_ids=None, venues=None,
                           base_url='http://localhost:8501', skip_existing=True,
                           sra_only=False, publish=False,
                           timeout_sra=180, timeout_elim=90, with_signal=True):
    """scripts/batch_sra_publish.py を独立プロセスとして起動する。

    Streamlitのセッションをブロックしないため、UIからはこれを呼び、
    進捗は read_status() でポーリングする。戻り値: pid(失敗時 None)。
    """
    import subprocess
    script = os.path.join(ROOT, 'scripts', 'batch_sra_publish.py')
    cmd = [sys.executable, script, '--url', base_url,
           '--timeout-sra', str(timeout_sra), '--timeout-elim', str(timeout_elim)]
    if race_ids:
        cmd += ['--race-ids', ','.join(str(r) for r in race_ids)]
    elif date_str:
        cmd += ['--date', str(date_str)]
    if venues:
        cmd += ['--venues', ','.join(venues)]
    cmd += ['--skip-existing'] if skip_existing else ['--no-skip-existing']
    cmd += ['--with-signal'] if with_signal else ['--no-signal']
    if sra_only:
        cmd.append('--sra-only')
    if publish:
        cmd.append('--publish')

    kwargs = {'cwd': ROOT, 'stdout': subprocess.DEVNULL,
              'stderr': subprocess.DEVNULL, 'stdin': subprocess.DEVNULL}
    if os.name == 'nt':
        # 親(Streamlit)を閉じてもバッチが巻き添えで死なないよう切り離す
        kwargs['creationflags'] = (subprocess.CREATE_NEW_PROCESS_GROUP
                                   | getattr(subprocess, 'DETACHED_PROCESS', 0))
    else:
        kwargs['start_new_session'] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
        return proc.pid
    except Exception:
        return None


def run_batch(date_str, race_ids_override=None, venues=None,
              base_url='http://localhost:8501', skip_existing=True,
              headless=True, sra_only=False, timeout_sra=180, timeout_elim=90,
              on_progress=None, with_signal=True):
    """指定日(または明示的なrace_ids)を一括解析する。

    on_progress(i, n, race_id, result) が各レース完了ごとに呼ばれる(任意)。
    戻り値: {'targets': [...], 'results': [...], 'ok': n, 'skipped': n, 'failed': n}
    """
    from playwright.sync_api import sync_playwright

    if race_ids_override:
        targets = [{'race_id': str(r), 'race_num': '', 'race_name': '', 'venue': ''}
                   for r in race_ids_override]
    else:
        targets = fetch_day_race_ids(date_str, venues=venues)

    results = []
    n = len(targets)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        try:
            for i, t in enumerate(targets, 1):
                rid = t['race_id']
                view_ok, elim_ok = _has_snapshots(rid)
                if skip_existing and view_ok and (sra_only or elim_ok):
                    res = {'race_id': rid, 'status': 'skipped', 'error': None,
                           'elapsed_s': 0.0, 'stage': 'skip'}
                    results.append(res)
                    if on_progress:
                        on_progress(i, n, rid, res)
                    continue
                sra_res = run_sra_for_race(browser, base_url, rid,
                                           timeout_s=timeout_sra,
                                           with_signal=with_signal)
                if sra_res['status'] == 'failed':
                    results.append(sra_res)
                    if on_progress:
                        on_progress(i, n, rid, sra_res)
                    continue
                if sra_only:
                    results.append(sra_res)
                    if on_progress:
                        on_progress(i, n, rid, sra_res)
                    continue
                elim_res = run_elim_filter_for_race(browser, base_url, rid,
                                                     timeout_s=timeout_elim)
                combined = {
                    'race_id': rid,
                    'status': elim_res['status'] if sra_res['status'] == 'ok' else sra_res['status'],
                    'stage': 'sra+elim',
                    'elapsed_s': round(sra_res['elapsed_s'] + elim_res['elapsed_s'], 1),
                    'error': elim_res.get('error') or sra_res.get('error'),
                }
                results.append(combined)
                if on_progress:
                    on_progress(i, n, rid, combined)
        finally:
            browser.close()

    ok = sum(1 for r in results if r['status'] == 'ok')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    failed = n - ok - skipped
    return {'targets': targets, 'results': results, 'ok': ok,
            'skipped': skipped, 'failed': failed}


def _load_newspaper_opts():
    """user_prefs.json の 'newspaper' キーを読む(未保存ならNone=build_newspaper_htmlの既定を使う)。"""
    try:
        with open(PREFS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f).get('newspaper') or None
    except Exception:
        return None


def publish_newspaper(race_ids, opts=None, out_dir=None, title_suffix=''):
    """race_idsをまとめて新聞PDF/HTMLとして書き出す(ブラウザ操作なし)。

    戻り値: {'pdf_path','html_path','meta_path','n'} または エラー時 None。
    """
    out_dir = out_dir or ISSUES_DIR
    os.makedirs(out_dir, exist_ok=True)
    if opts is None:
        opts = _load_newspaper_opts()

    html, issued = _np.build_newspaper_html(race_ids, opts)
    if not html:
        return None

    ts = time.strftime('%Y%m%d_%H%M%S')
    fname = f"shimbun_{ts}{title_suffix}"
    html_path = os.path.join(out_dir, fname + '.html')
    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html)

    pdf_path = None
    try:
        o = dict(_np.DEFAULT_OPTS)
        o.update(opts or {})
        pdf_fmt, landscape = _np.resolve_page_format(o.get('orientation', 'landscape'))
        pdf_bytes = _np.html_to_pdf(html, landscape=landscape, page_format=pdf_fmt,
                                    scale=o.get('scale', 1.0),
                                    page_numbers=o.get('page_numbers', True))
        pdf_path = os.path.join(out_dir, fname + '.pdf')
        with open(pdf_path, 'wb') as f:
            f.write(pdf_bytes)
    except Exception:
        pdf_path = None

    meta_path = os.path.join(out_dir, fname + '.meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({'race_ids': race_ids, 'issued': issued, 'opts': opts,
                   'ts': ts}, f, ensure_ascii=False, indent=2, default=str)

    return {'pdf_path': pdf_path, 'html_path': html_path,
            'meta_path': meta_path, 'n': len(issued)}
