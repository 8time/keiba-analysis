# -*- coding: utf-8 -*-
"""
JV-Link 接続＆読込テスト（32bit Python専用）
無料体験中・利用キー空でOK。option=1（通常データ）で取得する。

実行: C:\\Users\\kimnhaty\\pythonx86-312\\tools\\python.exe scripts\\jvlink_test.py
"""
import sys, io, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import win32com.client.dynamic

def code_of(r):
    return r[0] if isinstance(r, (tuple, list)) else r

def main():
    print("=== JV-Link 接続＆読込テスト ===")
    # 動的ディスパッチに固定（型付きgen_pyラッパーを避ける）
    jv = win32com.client.dynamic.Dispatch("JVDTLab.JVLink")
    rc = jv.JVInit("UNKNOWN")
    print(f"JVInit rc={rc}")
    if rc != 0:
        return

    # option=1（通常データ）、RACE系、直近から
    r = jv.JVOpen("RACE", "20260601000000", 1)
    rc = code_of(r)
    readcount = r[1] if isinstance(r, (tuple, list)) and len(r) > 1 else "?"
    dlcount = r[2] if isinstance(r, (tuple, list)) and len(r) > 2 else "?"
    print(f"JVOpen rc={rc} 読込予定={readcount}ファイル ダウンロード={dlcount}ファイル")
    if rc != 0:
        print("JVOpen失敗")
        return

    # レコード種別ごとの件数を集計しながら読む
    from collections import Counter
    kinds = Counter()
    total = 0
    waits = 0
    samples = []
    while total < 200:  # テストなので最大200レコード
        ret = jv.JVRead("", 120000, "")
        rc = ret[0] if isinstance(ret, (tuple, list)) else ret
        data = ret[1] if isinstance(ret, (tuple, list)) and len(ret) > 1 else ""
        if rc == 0:
            print("  [EOF] 全データ読込完了")
            break
        elif rc == -1:
            continue  # ファイル切替
        elif rc == -3:
            # ダウンロード中。少し待つ
            waits += 1
            if waits > 60:
                print("  ダウンロード待ちタイムアウト")
                break
            time.sleep(1)
            continue
        elif rc > 0:
            kind = str(data)[:2] if data else "??"
            kinds[kind] += 1
            total += 1
            if len(samples) < 6:
                samples.append((kind, str(data)[:60]))
        else:
            print(f"  rc={rc} で停止")
            break

    jv.JVClose()
    print(f"\n=== 読込 {total} レコード ===")
    print("レコード種別内訳:", dict(kinds))
    print("サンプル:")
    for k, s in samples:
        print(f"  [{k}] {s!r}")
    print("\n★ JRA-VANから実データ取得成功" if total > 0 else "データ0件")

if __name__ == "__main__":
    main()
