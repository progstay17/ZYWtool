"""handreport - pembuat laporan HTML hasil hand check (satu file mandiri, bisa dikirim apa adanya).
ZYWtool contributors

build_report(entries, meta, out_path, mode, title)
  mode="session": satu sesi, lengkap (vonis, garis waktu, frame bermasalah, galeri gambar)
  mode="group"  : satu folder grup / satu orang, tabel semua sesinya + link ke laporan tiap sesi
entry: {name, group, path, recorder, location, start, duration_min, health, hand, note, link}
       hand = hasil handcheck.analyze_session (atau None kalau dilewati / gagal)
"""
import base64
import html
import io
import os
import urllib.parse

CSS = """
:root{--bg:#F4F5F7;--surface:#fff;--ink:#16181D;--muted:#6B7280;--line:#E5E7EB;--dark:#111317;
--accent:#B9F36A;--ok:#23845B;--okbg:#E7F3E9;--flag:#C44949;--flagbg:#FCE9E8;--warn:#B7791F;--warnbg:#FFF3D9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 "Segoe UI",system-ui,-apple-system,sans-serif}
header{background:var(--dark);color:#fff;padding:26px 40px}
header h1{margin:0 0 4px;font-size:22px;font-weight:600;word-break:break-all}
header .sub{color:#9CA3AF;font-size:13px}header .credit{margin-top:10px;color:var(--accent);font-size:12px}
main{max-width:1180px;margin:0 auto;padding:22px 40px 60px}
.cards{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:18px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 18px}
.card .k{font-size:11px;font-weight:700;color:var(--muted);letter-spacing:.6px;text-transform:uppercase}
.card .v{font-size:26px;font-weight:600;margin-top:2px}.card .h{font-size:12px;color:var(--muted)}
.card.flag .v{color:var(--flag)}.card.ok .v{color:var(--ok)}
.verdict{border-radius:10px;padding:16px 20px;font-size:17px;font-weight:600;margin-bottom:16px}
.v-FLAG{background:var(--flagbg);color:var(--flag);border:1px solid #F2C4C1}
.v-OK{background:var(--okbg);color:var(--ok);border:1px solid #BFE0CB}
.v-ERROR,.v-SKIP{background:var(--warnbg);color:var(--warn);border:1px solid #EBD39B}
details.how{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:12px 18px;margin:18px 0}
details.how summary{cursor:pointer;font-weight:600}details.how ul{margin:10px 0 2px;padding-left:20px;color:#374151}
h2{font-size:14px;margin:22px 0 10px;letter-spacing:.3px}
table{width:100%;border-collapse:collapse;background:var(--surface);border:1px solid var(--line);
border-radius:10px;overflow:hidden}
th{background:#F7F8FA;text-align:left;font-size:11px;letter-spacing:.5px;color:#555B65;padding:9px 10px;
text-transform:uppercase}td{padding:9px 10px;border-top:1px solid var(--line);vertical-align:middle}
tr.flag td:first-child{box-shadow:inset 3px 0 0 var(--flag)}
.badge{display:inline-block;padding:2px 10px;border-radius:99px;font-size:11px;font-weight:700;letter-spacing:.4px}
.b-FLAG{background:var(--flagbg);color:var(--flag)}.b-OK{background:var(--okbg);color:var(--ok)}
.b-ERROR,.b-SKIP{background:var(--warnbg);color:var(--warn)}
.bar{height:8px;background:#EEF0F3;border-radius:4px;min-width:80px;position:relative;overflow:hidden;margin-top:3px}
.bar i{position:absolute;left:0;top:0;bottom:0;border-radius:4px}.bar u{position:absolute;top:0;bottom:0;width:2px;background:#111}
.tl{display:flex;height:14px;gap:1px;min-width:150px}.tl i{flex:1;border-radius:2px;background:var(--ok);opacity:.85}
.tl i.e{background:var(--flag);opacity:1}
.mono{font-family:Consolas,monospace;font-size:12px}.muted{color:var(--muted)}
a{color:inherit}.name a{font-weight:600;text-decoration:none}.name a:hover{text-decoration:underline}
.panel{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 20px;margin-bottom:16px}
.panel h3{margin:0 0 8px;font-size:14px}
.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:0 0 14px}
.grid div{background:#F7F8FA;border-radius:8px;padding:8px 12px}.grid b{display:block;font-size:11px;
color:var(--muted);letter-spacing:.5px;text-transform:uppercase}.grid span{font-size:18px;font-weight:600}
.frames{margin:6px 0;padding-left:18px;color:#374151}.frames li{margin:2px 0}
img.sheet{max-width:100%;border-radius:8px;border:1px solid var(--line);margin-top:8px}
.legend{font-size:12px;color:var(--muted);margin-top:4px}.legend i{display:inline-block;width:10px;height:10px;
border-radius:2px;vertical-align:middle;margin:0 3px 0 10px}
footer{text-align:center;color:var(--muted);font-size:12px;padding:24px}
@media print{header{background:#fff;color:#000;border-bottom:2px solid #000}.panel{break-inside:avoid}
details.how{display:none}}
@media(max-width:800px){.cards,.grid{grid-template-columns:repeat(2,1fr)}main{padding:16px}}
"""

esc = html.escape


def _img_b64(path, max_w=1400):
    if not path or not os.path.exists(path):
        return ""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGB")
        if im.width > max_w:
            im = im.resize((max_w, int(im.height * max_w / im.width)))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:
        return ""


def _status(e):
    h = e.get("hand")
    if h and h.get("frames"):
        return "FLAG" if h.get("flag") else "OK"
    return "SKIP" if (e.get("note") or "").startswith("dilewati") else "ERROR"


def _reason(f, rule):
    parts = []
    if f["n"] == 0:
        parts.append("tidak ada tangan")
    elif f["n"] == 1 and rule == "strict":
        parts.append("hanya 1 tangan")
    elif f["n"] > 2:
        parts.append(f"{f['n']} tangan (lebih dari 2: tangan orang lain / kaki)")
    if f["out"]:
        parts.append("tangan keluar frame")
    return "; ".join(parts)


def _mmss(t):
    return f"{int(t) // 60:02d}:{int(t) % 60:02d}"


def _fmt(v, nd=0):
    return f"{v:.{nd}f}".replace(".", ",")


def _thousands(n):
    return f"{int(n):,}".replace(",", ".")


def _sort_key(e):
    pct = (e.get("hand") or {}).get("pct", 0)
    return ({"FLAG": 0, "ERROR": 1, "SKIP": 2, "OK": 3}[_status(e)], -pct)


def _timeline(h, rule):
    cells = []
    for f in h.get("detail") or []:
        bad = bool(_reason(f, rule))
        tip = f"{_mmss(f['t'])} - {f['n']} tangan" + (" (keluar frame)" if f["out"] else "")
        cells.append('<i class="' + ("e" if bad else "g") + '" title="' + esc(tip) + '"></i>')
    return '<div class="tl">' + "".join(cells) + "</div>" if cells else ""


def _sampling(meta):
    every = float(meta.get("every") or 0)
    if every > 0:
        return (f"(sekitar 1 sampel tiap {every:g} detik, minimal {meta.get('min_frames', 20)} "
                f"dan maksimal {meta.get('max_frames', 120)} frame)")
    return f"(tepat {meta.get('frames', 20)} frame sampel)"


def _how(meta):
    rule = meta.get("rule", "strict")
    thr = _fmt(float(meta.get("max", 30)))
    rule_txt = ("error kalau jumlah tangan bukan 2, atau ada titik tangan di luar frame" if rule == "strict"
                else "error kalau tangan = 0, tangan lebih dari 2, atau ada titik tangan di luar frame")
    return (
        '<details class="how"><summary>Cara membaca laporan ini</summary><ul>'
        f'<li><b>Metode:</b> bukan semua frame yang diperiksa. Frame diambil merata sepanjang sesi {_sampling(meta)}, '
        f'lalu tiap frame diperiksa MediaPipe '
        f'(frame penuh + 4 potongan, ambang {esc(str(meta.get("conf", 0.3)))}).</li>'
        f'<li><b>Aturan aktif ({esc(rule)}):</b> {rule_txt}. Tangan lebih dari 2 berarti ada tangan orang lain '
        'atau jari kaki yang terbaca sebagai tangan.</li>'
        f'<li><b>Frame error %</b> = frame bermasalah dibagi frame sampel. Sesi ditandai FLAG kalau melebihi batas {thr}%.</li>'
        '<li><b>Perkiraan 95%</b> adalah rentang kemungkinan nilai sebenarnya. Kalau batas masuk ke dalam rentang, '
        'naikkan jumlah sampel.</li>'
        '<li><b>Keterbatasan:</b> deteksi bersifat probabilistik (mis. dua tangan menumpuk bisa terbaca satu). '
        'Jari kaki hanya terdeteksi kalau kebetulan terbaca sebagai tangan. Gunakan sebagai penanda untuk dicek '
        'manual lewat gambar.</li></ul></details>')


def _page(title, sub, credit, body, footer_credit):
    return (f'<!doctype html><html lang="id"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(title)}</title><style>{CSS}</style></head><body>'
            f'<header><h1>{esc(title)}</h1><div class="sub">{sub}</div><div class="credit">{esc(credit)}</div></header>'
            f'<main>{body}</main><footer>{esc(footer_credit)}</footer></body></html>')


def _session_body(e, meta):
    rule = meta.get("rule", "strict")
    thr = float(meta.get("max", 30))
    st = _status(e)
    h = e.get("hand") or {}
    out = []
    if not h.get("frames"):
        out.append(f'<div class="verdict v-{st}">{st} - {esc(e.get("note") or h.get("note") or "tidak ada hasil")}</div>')
        out.append(_how(meta))
        return "".join(out)
    word = "melebihi" if h.get("flag") else "di bawah"
    out.append(f'<div class="verdict v-{st}">{st} - {_fmt(h["pct"])}% frame error ({esc(rule)}), '
               f'{word} batas {_fmt(thr)}%</div>')
    lo, hi = h.get("ci", [0, 0])
    out.append('<div class="grid">'
               f'<div><b>Error ({esc(rule)})</b><span>{_fmt(h["pct"])}%</span></div>'
               f'<div><b>Strict / Lenient</b><span>{_fmt(h["pct_strict"])}% / {_fmt(h["pct_lenient"])}%</span></div>'
               f'<div><b>Perkiraan 95%</b><span>{_fmt(lo)}-{_fmt(hi)}%</span></div>'
               f'<div><b>Batas</b><span>{_fmt(thr)}%</span></div></div>')
    c = h["counts"]
    tot = h.get("total_frames")
    cov = f'{h["frames"]} frame sampel'
    if tot:
        cov = (f'{h["frames"]} dari sekitar {_thousands(tot)} frame ({_fmt(100 * h["frames"] / tot, 2)}%), '
               f'1 sampel tiap sekitar {h.get("interval_s", 0):.0f} detik')
    out.append('<div class="panel"><h3>Cakupan &amp; sebaran</h3>'
               f'<div class="muted">{esc(cov)}. Tangan terdeteksi 0 / 1 / 2 / 3+ : '
               f'<span class="mono">{c["0"]} / {c["1"]} / {c["2"]} / {c["3+"]}</span></div>'
               f'<div style="margin-top:10px">{_timeline(h, rule)}</div>'
               '<div class="legend"><i style="background:var(--ok)"></i>frame lolos'
               '<i style="background:var(--flag)"></i>frame bermasalah (kiri = awal sesi, kanan = akhir)</div></div>')
    if h.get("skipped_files"):
        out.append('<div class="panel"><b>Catatan:</b> file tidak terbaca dan dilewati: '
                   f'{esc(", ".join(h["skipped_files"]))}</div>')
    bad = [f for f in h.get("detail", []) if _reason(f, rule)]
    if bad:
        shown = bad[:40]
        more = f'<li class="muted">... dan {len(bad) - len(shown)} frame lain</li>' if len(bad) > len(shown) else ""
        out.append('<div class="panel"><h3>Frame bermasalah</h3><ul class="frames">' +
                   "".join(f'<li><span class="mono">{_mmss(f["t"])}</span> (frame #{f["idx"]}) - '
                           f'{esc(_reason(f, rule))}</li>' for f in shown) + more + "</ul>")
        img = _img_b64(h.get("errors_sheet"))
        if img:
            out.append(f'<img class="sheet" src="{img}" alt="frame bermasalah">')
        out.append("</div>")
    else:
        out.append('<div class="panel muted">Tidak ada frame bermasalah pada sampel.</div>')
    img = _img_b64(h.get("sheet"))
    if img:
        out.append('<div class="panel"><h3>Semua frame sampel</h3>'
                   f'<img class="sheet" src="{img}" alt="semua frame sampel"></div>')
    out.append(_how(meta))
    return "".join(out)


def _group_body(entries, meta, title):
    rule = meta.get("rule", "strict")
    thr = float(meta.get("max", 30))
    ents = sorted(entries, key=_sort_key)
    n_flag = sum(1 for e in ents if _status(e) == "FLAG")
    n_ok = sum(1 for e in ents if _status(e) == "OK")
    n_other = len(ents) - n_flag - n_ok
    rows = []
    for e in ents:
        st = _status(e)
        h = e.get("hand") or {}
        link = e.get("link")
        nm = esc(e["name"])
        name_html = f'<a href="{esc(urllib.parse.quote(link))}">{nm}</a>' if link else nm
        if h.get("frames"):
            c = h["counts"]
            pct = h["pct"]
            color = "var(--flag)" if h.get("flag") else "var(--ok)"
            lo, hi = h.get("ci", [None, None])
            ci = f"{_fmt(lo)}-{_fmt(hi)}%" if lo is not None else "-"
            cells = (f'<td class="mono">{c["0"]} / {c["1"]} / {c["2"]} / {c["3+"]}</td>'
                     f'<td><b>{_fmt(pct)}%</b><div class="bar"><i style="width:{min(pct, 100):.0f}%;background:{color}"></i>'
                     f'<u style="left:{min(thr, 100):.0f}%"></u></div></td>'
                     f'<td>{_timeline(h, rule)}</td>'
                     f'<td class="muted">{_fmt(h["pct_strict"])}% / {_fmt(h["pct_lenient"])}%</td>'
                     f'<td class="muted">{ci}</td>')
        else:
            cells = f'<td colspan="5" class="muted">{esc(e.get("note") or h.get("note") or "-")}</td>'
        dur = (_fmt(e["duration_min"], 1) + " mnt") if e.get("duration_min") is not None else "-"
        rows.append(f'<tr class="{"flag" if st == "FLAG" else ""}"><td><span class="badge b-{st}">{st}</span></td>'
                    f'<td class="name">{name_html}</td><td>{esc(e.get("recorder") or "-")}</td>'
                    f'<td class="mono">{esc(e.get("start") or "-")}</td><td class="mono">{dur}</td>'
                    f'<td class="mono">{h.get("frames", "-")}</td>{cells}</tr>')
    return (
        '<div class="cards">'
        f'<div class="card"><div class="k">Sesi diperiksa</div><div class="v">{len(ents)}</div><div class="h">{n_ok + n_flag} dianalisis</div></div>'
        f'<div class="card flag"><div class="k">Ditandai FLAG</div><div class="v">{n_flag}</div><div class="h">error di atas {_fmt(thr)}%</div></div>'
        f'<div class="card ok"><div class="k">Lolos</div><div class="v">{n_ok}</div><div class="h">error maksimal {_fmt(thr)}%</div></div>'
        f'<div class="card"><div class="k">Dilewati / gagal</div><div class="v">{n_other}</div><div class="h">alasan ada di tabel</div></div></div>'
        '<h2>Ringkasan per sesi</h2><table><thead><tr><th>Status</th><th>Sesi</th><th>Recorder</th><th>Mulai</th>'
        f'<th>Durasi</th><th>Sampel</th><th>Tangan 0/1/2/3+</th><th>Error ({esc(rule)})</th><th>Garis waktu</th>'
        '<th>Strict / Lenient</th><th>95%</th></tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
        '<div class="legend"><i style="background:var(--ok)"></i>frame lolos<i style="background:var(--flag)"></i>'
        'frame bermasalah. Klik nama sesi untuk membuka laporan lengkapnya.</div>' + _how(meta))


def build_report(entries, meta, out_path, mode="group", title=None):
    credit = meta.get("credit", "")
    gen = f'{esc(meta.get("generated", ""))}'
    if mode == "session":
        e = entries[0]
        sub = (f'{gen} &middot; {esc(e.get("group") or "-")} &middot; {esc(e.get("recorder") or "-")} &middot; '
               f'{esc(e.get("location") or "-")} &middot; mulai {esc(e.get("start") or "-")}')
        doc = _page("Hand Check - " + e["name"], sub, credit, _session_body(e, meta), credit)
    else:
        sub = f'{gen} &middot; {len(entries)} sesi &middot; sumber: {esc(str(meta.get("source", "-")))}'
        doc = _page("Hand Check - " + (title or "grup"), sub, credit, _group_body(entries, meta, title), credit)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    tmp = out_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(doc)
    os.replace(tmp, out_path)
    return out_path

