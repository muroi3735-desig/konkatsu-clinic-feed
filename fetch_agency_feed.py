
    # ミチ婚（十川悦子・大阪心斎橋）＝2026-09-25に掲載6社目として追加。
    # サイト直下の /feed/ は記事0件（ブログが独自の投稿タイプ）。ブログ用の /blog/feed/ を使う（9/25 CO確認＝10件）。
    {"agencyId": "michikon", "name": "心斎橋の結婚相談所ミチ婚", "kind": "rss",
     "url": "https://michikon.jp/blog/feed/",
     "imageHost": "michikon.jp", "media": "ブログ"},# -*- coding: utf-8 -*-
"""
婚活クリニックLP「相談所の発信」枠のデータ取得スクリプト（1日1回実行）。

出力＝agency-feed.json（LPはこのJSONだけを読む。取得の仕組みとLPの表示を切り離す）。
2026-09-18にCOが各社の公開フィードを実機で確認したうえで書いた仕様です。

実行例:
    python3 fetch_agency_feed.py --out agency-feed.json

取得できないとき（相手サイトの障害・仕様変更）は、前回のJSONをそのまま残します。
空のJSONで上書きしないこと（LPの枠が消えるため）。
"""
import argparse, json, re, sys, time
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
from urllib.request import urlopen, Request
from xml.etree import ElementTree as ET

UA = "meets-lab clinic feed reader/1.0 (+https://meets-lab.com/clinic)"
TIMEOUT = 40
RETRIES = 3
NS = {"content": "http://purl.org/rss/1.0/modules/content/",
      "media": "http://search.yahoo.com/mrss/",
      "atom": "http://www.w3.org/2005/Atom",
      "yt": "http://www.youtube.com/xml/schemas/2015"}

# 相談所ごとの取得元。agencyId は LP 側のカード ID と一致させること。
SOURCES = [
    {"agencyId": "happiness", "name": "ハピネス婚サルティング", "kind": "rss",
     "url": "https://www.happiness-consulting.wedding/feed/",
     "imageHost": "happiness-consulting.wedding", "media": "ブログ"},
    {"agencyId": "blue-star", "name": "婚活サポート ブルースター", "kind": "rss",
     "url": "https://www.blue-star.info/feed/",
     "imageHost": "blue-star.info", "media": "ブログ"},
    {"agencyId": "marl", "name": "結婚相談所marl（マール）", "kind": "rss",
     "url": "https://bridal-marl.com/feed/",
     "imageHost": "bridal-marl.com", "media": "ブログ"},
    {"agencyId": "gon", "name": "ゴンちゃんの結婚相談所", "kind": "youtube",
     # 2026-09-24: channel_id 形式のフィードが404になったため、アップロード再生リスト（UU…）のフィードを使う。
     "url": "https://www.youtube.com/feeds/videos.xml?playlist_id=UUKNsTY9-KKiYu_1CWjfWRZA",
     "media": "YouTube"},
    # エトワールマリッジナオ＝2026-09-21に発信URLを受領（エトワール→山本さんへのLINE）。
    # ブログ名「ナースがはじめた神戸の結婚相談所」／運営者名の表記は「ナオ」。
    # フィードは rss20.xml を使う（RSS 2.0・10件・pubDateあり）。
    # rss.html の方はRSS 1.0（RDF）で、このスクリプトの parse_rss では0件になるため使わない。
    # 画像は stat*.ameba.jp に置かれるため imageHost は "ameba.jp"（記事URLは ameblo.jp）。
    {"agencyId": "etoile", "name": "エトワールマリッジナオ", "kind": "rss",
     "url": "https://rssblog.ameba.jp/eri12yuka6/rss20.xml",
     "imageHost": "ameba.jp", "media": "ブログ"},
    # ミチ婚（十川悦子・大阪心斎橋）＝2026-09-25に掲載6社目として追加。
    # サイト直下の /feed/ は記事0件（ブログが独自の投稿タイプ）。ブログ用の /blog/feed/ を使う（9/25 CO確認＝10件）。
    {"agencyId": "michikon", "name": "心斎橋の結婚相談所ミチ婚", "kind": "rss",
     "url": "https://michikon.jp/blog/feed/",
     "imageHost": "michikon.jp", "media": "ブログ"},
]

DROP_PARAMS = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "fbclid", "gclid")


def fetch(url):
    """相手サイトが遅いときのために最大3回まで取り直す。"""
    last = None
    for n in range(RETRIES):
        try:
            return urlopen(Request(url, headers={"User-Agent": UA}), timeout=TIMEOUT).read()
        except Exception as ex:
            last = ex
            time.sleep(3 * (n + 1))
    raise last


def clean_url(u):
    """RSS由来の計測パラメータを外す。ハピネスのフィードは utm_* が必ず付く。"""
    if not u:
        return u
    p = urlparse(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query) if k not in DROP_PARAMS]
    return urlunparse(p._replace(query=urlencode(q)))


def https(u):
    """ブルースターのフィードは画像URLが http:// で返る。https へ寄せる（到達確認済み）。"""
    return re.sub(r"^http://", "https://", u or "")


def strip_tags(h):
    h = re.sub(r"(?is)<(script|style).*?</\1>", " ", h or "")
    h = re.sub(r"(?s)<[^>]+>", " ", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&#8230;", "…").replace("&quot;", '"'))
    return re.sub(r"\s+", " ", h).strip()


def pick_image(html_fragments, image_host):
    """本文中の最初の img を無条件に採らない。
    絵文字（s.w.org）やSNSボタン（scdn.line-apps.com）が先頭に来る記事が実在する。
    その相談所のドメインの画像だけを採用する。"""
    for frag in html_fragments:
        for m in re.finditer(r'<img[^>]+src="([^"]+)"', frag or ""):
            u = https(m.group(1))
            if image_host in u and "/emoji/" not in u:
                return u
    return None


def og_image(page_url, image_host):
    """フィードに画像が無い相談所（ハピネス）向け。記事ページの og:image を読む。"""
    try:
        html = fetch(page_url).decode("utf-8", "ignore")
    except Exception:
        return None
    m = (re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html)
         or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html))
    if not m:
        return None
    u = https(m.group(1))
    return u if image_host in u else None


def parse_rss(xml, src, limit):
    root = ET.fromstring(xml)
    out = []
    for item in root.findall("./channel/item")[:limit]:
        link = clean_url(item.findtext("link"))
        enc = item.findtext("content:encoded", default="", namespaces=NS)
        desc = item.findtext("description", default="")
        img = pick_image([enc, desc], src["imageHost"]) or og_image(link, src["imageHost"])
        text = strip_tags(desc) or strip_tags(enc)
        text = re.sub(r"\s*…?\s*(続きを読む|Read more).*$", "", text)[:110]
        out.append({
            "agencyId": src["agencyId"], "agencyName": src["name"], "media": src["media"],
            "title": (item.findtext("title") or "").strip(),
            "url": link,
            "publishedAt": to_iso(item.findtext("pubDate")),
            "thumbnail": img,
            "excerpt": text,
        })
    return out


def parse_youtube(xml, src, limit, include_shorts):
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("atom:entry", NS)[:limit * 2]:
        link = e.find("atom:link", NS).get("href")
        is_short = "/shorts/" in link
        if is_short and not include_shorts:
            continue
        g = e.find("media:group", NS)
        th = g.find("media:thumbnail", NS) if g is not None else None
        out.append({
            "agencyId": src["agencyId"], "agencyName": src["name"],
            "media": "YouTube（ショート）" if is_short else "YouTube",
            "title": (e.findtext("atom:title", default="", namespaces=NS)).strip(),
            "url": link,
            "publishedAt": (e.findtext("atom:published", default="", namespaces=NS)),
            "thumbnail": th.get("url") if th is not None else None,
            # media:description は宣伝文とリンクが中心のため冒頭文には使わない。
            "excerpt": "",
        })
        if len(out) >= limit:
            break
    return out


def to_iso(pub):
    for f in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
        try:
            return datetime.strptime((pub or "").strip(), f).astimezone(timezone.utc).isoformat()
        except Exception:
            pass
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="agency-feed.json")
    ap.add_argument("--per-agency", type=int, default=6)
    ap.add_argument("--include-shorts", action="store_true")
    a = ap.parse_args()

    items, errors = [], []
    for src in SOURCES:
        try:
            xml = fetch(src["url"])
            got = (parse_youtube(xml, src, a.per_agency, a.include_shorts) if src["kind"] == "youtube"
                   else parse_rss(xml, src, a.per_agency))
            items.extend(got)
            print("OK  %-10s %d件" % (src["agencyId"], len(got)), file=sys.stderr)
        except Exception as ex:
            errors.append({"agencyId": src["agencyId"], "error": str(ex)})
            print("NG  %-10s %s" % (src["agencyId"], ex), file=sys.stderr)
        time.sleep(1)  # 相手サーバへ連続アクセスしない

    # 取得に失敗した相談所は、前回のJSONに入っていた分をそのまま残す（一時的な失敗で枠から消さない）。
    try:
        prev = json.load(open(a.out, encoding="utf-8")).get("items", [])
    except Exception:
        prev = []
    failed = {e["agencyId"] for e in errors}
    items.extend(i for i in prev if i.get("agencyId") in failed)

    if not items:
        print("取得0件のため既存のJSONを残します（空で上書きしない）", file=sys.stderr)
        sys.exit(1)

    items.sort(key=lambda i: i["publishedAt"] or "", reverse=True)
    json.dump({"generatedAt": datetime.now(timezone.utc).isoformat(),
               "errors": errors, "items": items},
              open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print("wrote %s (%d件)" % (a.out, len(items)), file=sys.stderr)


if __name__ == "__main__":
    main()
