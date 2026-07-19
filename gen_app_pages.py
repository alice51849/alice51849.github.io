#!/usr/bin/env python3
"""
為每個 app 生成靜態 SEO 落地頁 (app/{slug}/index.html)。
- 靜態完整內容(爬蟲/AI 直接讀,不靠 JS)
- SoftwareApplication + FAQPage schema (結構化資料)
- AI 生成獨特豐富內容(描述 + FAQ),避免薄內容
- 暖色系響應式,複用品牌調性
用法:
  OPENAI_KEY=... python3 gen_app_pages.py --slug cvdesk        # 單一示範
  OPENAI_KEY=... python3 gen_app_pages.py --all                # 全部(冪等,已存在跳過)
  OPENAI_KEY=... python3 gen_app_pages.py --all --force        # 強制重生
  python3 gen_app_pages.py --sitemap                           # 只重建 sitemap
   python3 scripts/sync_root_app_pages.py                       # 雲端 deterministic live sync
"""
import os, sys, json, re, argparse, subprocess, urllib.request, urllib.error, time

SITE = os.path.dirname(os.path.abspath(__file__))
APPS_JSON = os.path.expanduser("~/threads-autopilot/apps.json")
BASE = "https://alice51849.github.io"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

# slug→(icon 檔名, 截圖檔名或 None) — github.io 既有資源命名
ICON = {  # threads slug → github.io icon slug
 "cvdesk":"cv-desk","sononote":"sono-note","unblurry":"unblurry-pro","zodira":"zodira",
 "aim990":"aim990","mochi":"mochi-todo","snapport":"snapport","picclear":"picclear-pro",
 "scanto":"scanto-pro","cyca":"cyca","gmoney":"g-money","hourstag":"hourstag",
 "lockhour":"lockhour-pro","photocream":"photocream-pro",
 "lumiletters":"lumi-letters-lite","lumimath":"lumi-math-planet","lumimission":"lumi-mission-planet",
 "lumiweather":"lumi-weather","lumiletterspro":"lumi-letters-pro","lumimathpro":"lumi-math-pro",
 "lumimissionpro":"lumi-mission-planet-pro","lumibopomofo":"lumi-bopomofo","lumibopomofopro":"lumi-bopomofo-pro",
}
SHOTS = {"lockhour":"lockhour-pro","lumibopomofo":"lumi-bopomofo","lumiletters":"lumi-letters-lite",
 "lumiletterspro":"lumi-letters-pro","lumimission":"lumi-mission-planet","lumiweather":"lumi-weather",
 "scanto":"scanto-pro"}

CAT_MAP = {
 "productivity":"BusinessApplication","finance":"FinanceApplication",
 "photo-utility":"MultimediaApplication","health":"HealthApplication",
 "lifestyle":"LifestyleApplication","kids":"EducationalApplication",
 "education":"EducationalApplication","travel":"TravelApplication",
 "sleep-sound":"LifestyleApplication",
}

# 多語言:UI 字串 + OpenAI 輸出語言。en 為主頁(app/{slug}/),其餘為 app/{slug}/{lang}/
LANGS = {
 "en": {"html":"en","cta":"Download on the App Store →","get":"Get {name} on the App Store →",
        "why":"Why {name}","features":"Features","faq":"Frequently asked questions",
        "made":"Made by Lumi Studio — pay once, no ads, privacy-first.","all":"All apps",
        "oai":"English (US)"},
 "zh": {"html":"zh-Hant","cta":"前往 App Store 下載 →","get":"在 App Store 下載 {name} →",
        "why":"為什麼選擇 {name}","features":"主要功能","faq":"常見問題",
        "made":"由 Lumi Studio 製作 — 一次買斷、無廣告、隱私優先。","all":"所有 App",
        "oai":"Traditional Chinese as written natively in Taiwan (zh-Hant-TW)"},
 "ja": {"html":"ja","cta":"App Store でダウンロード →","get":"{name} を App Store で入手 →",
        "why":"{name} が選ばれる理由","features":"主な機能","faq":"よくある質問",
        "made":"Lumi Studio 制作 — 買い切り・広告なし・プライバシー第一。","all":"すべてのアプリ",
        "oai":"natural native Japanese"},
 "ko": {"html":"ko","cta":"App Store에서 다운로드 →","get":"App Store에서 {name} 받기 →",
        "why":"{name}를 선택하는 이유","features":"주요 기능","faq":"자주 묻는 질문",
        "made":"Lumi Studio 제작 — 한 번 결제, 광고 없음, 개인정보 우선.","all":"모든 앱",
        "oai":"natural native Korean"},
}
LANG_ORDER = ["en","zh","ja","ko"]
HREFLANG = {"en":"en","zh":"zh-Hant","ja":"ja","ko":"ko"}


def parse_datajs(path):
    """解析 assets/data.js 的 window.APPS 陣列成 threads 相容 dict(雲端素材來源)。"""
    s = open(path, encoding="utf-8").read()
    i = s.find("window.APPS=["); b = s.find("[", i); depth = 0; end = len(s)
    for j in range(b, len(s)):
        if s[j] == "[": depth += 1
        elif s[j] == "]":
            depth -= 1
            if depth == 0: end = j + 1; break
    arr = json.loads(s[b:end])
    apps = {}
    for e in arr:
        slug = e.get("slug")
        if not slug: continue
        nm = e.get("name", {}); sb = e.get("sub", {}); bl = e.get("blurb", {})
        apps[slug] = {
            "name": (nm.get("en") or nm.get("zh") or slug).split(":")[0].strip(),
            "name_i18n": nm, "sub_i18n": sb, "blurb_i18n": bl,
            "url": e.get("url", ""), "category": e.get("cat", ""),
            "title": sb.get("en", ""), "sub": bl.get("en") or sb.get("en", ""),
            "kicker": (e.get("badge") or "APP").upper(), "cta_bullets": [], "keywords": [],
        }
    return apps


def load_apps():
    """素材來源優先序:APPS_SOURCE=datajs 強制 data.js > APPS_JSON env > threads apps.json(本地) > data.js(雲端)。"""
    dj = os.path.join(SITE, "assets", "data.js")
    if os.environ.get("APPS_SOURCE") == "datajs" and os.path.exists(dj):
        return parse_datajs(dj)
    env = os.environ.get("APPS_JSON", "")
    if env and os.path.exists(env):
        return json.load(open(env, encoding="utf-8"))
    if os.path.exists(APPS_JSON):
        return json.load(open(APPS_JSON, encoding="utf-8"))
    if os.path.exists(dj):
        return parse_datajs(dj)
    return {}


def _oaikey():
    p = os.path.expanduser("~/.openai_key")
    return (open(p).read().strip() if os.path.exists(p) else "") or os.environ.get("OPENAI_KEY","").strip()

def _openai_json(messages):
    key=_oaikey()
    if not key: print("no OpenAI key"); return None
    body=json.dumps({"model":MODEL,"messages":messages,"temperature":0.8,
                     "max_tokens":1500,"response_format":{"type":"json_object"}}).encode()
    req=urllib.request.Request("https://api.openai.com/v1/chat/completions",data=body,
        headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"})
    for a in range(4):
        try:
            with urllib.request.urlopen(req,timeout=90) as r:
                return json.loads(json.load(r)["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as e:
            if e.code==429: time.sleep(8*(a+1)); continue
            time.sleep(3*(a+1))
        except Exception: time.sleep(3*(a+1))
    return None

SYS="""You are a senior SEO copywriter writing a landing page for an iOS app. Output rich, UNIQUE, genuinely useful content that ranks well and that AI assistants (ChatGPT, Perplexity) would cite when recommending apps.
Return STRICT JSON:
{
 "meta": "<=155 char meta description, keyword-rich, compelling, plain text",
 "hero_line": "one punchy human sentence under the title",
 "intro": "1 paragraph (2-3 sentences) — the real problem this app solves, human and concrete",
 "sections": [ {"h":"section heading (benefit/use-case, keyword-aware)", "p":"1 short paragraph"} x3 ],
 "features": ["6 concise feature bullets, concrete"],
 "faqs": [ {"q":"natural long-tail question a real user googles", "a":"helpful 1-2 sentence answer"} x5 ]
}
Rules: sound human, specific, no fluff, no 'Introducing/Say goodbye/game-changer'. Weave in the app's real keywords naturally. FAQs should target real search intent (pricing, privacy, how-to, comparisons).
CRITICAL: Never claim whether the app needs internet or works offline — you don't know, so don't state it. Don't invent specific numbers, ratings, or technical specs not provided. For privacy/data questions, say it's privacy-first and never sells your data. For pricing, it's a one-time purchase with no subscription.
LANGUAGE: Write ALL fields (meta, hero_line, intro, sections, features, faqs) in the OUTPUT LANGUAGE the user specifies — as a native copywriter for that market, natural and idiomatic, never a literal translation. Keep the app's brand name in its original Latin spelling."""

def gen_content(app, lang="en"):
    g=lambda k: (app.get(k+"_i18n",{}) or {}).get(lang) or app.get(k,"")
    u=(f"App: {app['name']}\nTagline: {g('title')} — {g('sub')}\n"
       f"Category: {app.get('category','')}\nKeywords: {', '.join(app.get('keywords',[]))}\n"
       f"Selling points: {', '.join(app.get('cta_bullets',[]))}\nMonetization: one-time purchase (pay once), no subscription, privacy-first, no ads.\n"
       f"OUTPUT LANGUAGE: {LANGS[lang]['oai']}.\nWrite the landing page content as JSON now.")
    return _openai_json([{"role":"system","content":SYS},{"role":"user","content":u}])


def esc(s): return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;"))

PAGE="""<!DOCTYPE html>
<html lang="{htmllang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
{smart_banner}
<title>{title}</title>
<meta name="description" content="{meta}">
<link rel="canonical" href="{url}">
{hreflang}
<meta name="theme-color" content="#fffaf0">
<meta property="og:type" content="product">
<meta property="og:title" content="{ogtitle}">
<meta property="og:description" content="{meta}">
<meta property="og:image" content="{icon_abs}">
<meta property="og:url" content="{url}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="{icon}">
<link rel="apple-touch-icon" href="{icon}">
<script type="application/ld+json">
{schema}
</script>
<style>
:root{{--ink:#3c3119;--ink2:#665436;--muted:#857049;--line:#f1e7cf;--bg:#fffaf0;--card:#fffdf8;--a1:#ffc24e;--a2:#f3895a}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,"Noto Sans TC",sans-serif;color:var(--ink);background:var(--bg);line-height:1.6;-webkit-font-smoothing:antialiased}}
.wrap{{max-width:860px;margin:0 auto;padding:0 22px}}
a{{color:#c2622f;text-decoration:none}}
header.nav{{padding:18px 0}}
header .brand{{font-weight:800;font-size:18px;color:var(--ink);display:inline-flex;align-items:center;gap:8px}}
.hero{{text-align:center;padding:34px 0 12px}}
.hero img.app-icon{{width:104px;height:104px;border-radius:23px;box-shadow:0 10px 30px rgba(160,120,40,.22);margin-bottom:18px}}
.kicker{{font-size:12px;font-weight:800;letter-spacing:.14em;color:var(--a2);text-transform:uppercase}}
h1{{font-size:clamp(26px,5vw,38px);font-weight:800;margin:8px 0;letter-spacing:-.01em}}
.hero .sub{{font-size:18px;color:var(--ink2);max-width:600px;margin:0 auto 22px}}
.cta{{display:inline-flex;align-items:center;gap:9px;background:linear-gradient(135deg,var(--a1),var(--a2));color:#fff;font-weight:800;font-size:17px;padding:14px 30px;border-radius:14px;box-shadow:0 8px 22px rgba(243,137,90,.32);transition:transform .15s}}
.cta:hover{{transform:translateY(-2px)}}
.pills{{margin:16px 0 6px;display:flex;gap:8px;justify-content:center;flex-wrap:wrap}}
.pill{{font-size:13px;font-weight:600;color:var(--ink2);background:#fff;border:1px solid var(--line);border-radius:999px;padding:6px 13px}}
.shot{{display:block;max-width:300px;width:100%;margin:30px auto 0;border-radius:22px;box-shadow:0 16px 44px rgba(160,120,40,.2)}}
section{{padding:30px 0;border-top:1px solid var(--line)}}
section:first-of-type{{border-top:none}}
h2{{font-size:23px;font-weight:800;margin-bottom:14px}}
.intro{{font-size:18px;color:var(--ink2)}}
.feat{{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:6px}}
.feat div{{background:var(--card);border:1px solid var(--line);border-radius:13px;padding:14px 16px;font-weight:600;font-size:15px}}
.blk{{margin-bottom:20px}}
.blk h3{{font-size:18px;font-weight:800;margin-bottom:5px}}
.blk p{{color:var(--ink2)}}
.faq dt{{font-weight:800;margin-top:16px}}
.faq dd{{color:var(--ink2);margin:5px 0 0}}
.foot{{text-align:center;padding:34px 0;color:var(--muted);font-size:14px;border-top:1px solid var(--line);margin-top:14px}}
.foot a{{margin:0 8px}}
@media(max-width:560px){{.feat{{grid-template-columns:1fr}}}}
</style>
</head>
<body>
{generation_marker}
<div class="wrap">
<header class="nav"><a class="brand" href="/">✦ Lumi Studio</a></header>
<div class="hero">
<img class="app-icon" src="{icon}" alt="{name} app icon" width="104" height="104">
<div class="kicker">{kicker}</div>
<h1>{name}</h1>
<p class="sub">{hero_line}</p>
<a class="cta" href="{store}" rel="noopener">{c_cta}</a>
<div class="pills">{pills}</div>
{shot}
</div>
<section>
<p class="intro">{intro}</p>
</section>
<section>
<h2>{c_why}</h2>
{blocks}
</section>
<section>
<h2>{c_features}</h2>
<div class="feat">{features}</div>
</section>
<section class="faq">
<h2>{c_faq}</h2>
<dl>{faqs}</dl>
</section>
<div style="text-align:center;padding:8px 0 30px">
<a class="cta" href="{store}" rel="noopener">{c_get}</a>
</div>
</div>
<div class="foot">
<div>{c_made}</div>
<div style="margin-top:8px"><a href="/">{c_all}</a> · <a href="{store}" rel="noopener">App Store</a></div>
</div>
</body>
</html>
"""

def build_page(slug, app, content, lang="en"):
    L=LANGS[lang]
    gslug=ICON.get(slug,slug)
    icon=f"/assets/icons/{gslug}.png"; icon_abs=BASE+icon
    suffix="" if lang=="en" else f"{lang}/"
    url=f"{BASE}/app/{gslug}/{suffix}"
    store=app.get("url","")
    app_id_match=re.search(r"/id(\d+)(?:[/?]|$)", store)
    if not app_id_match:
        raise ValueError(f"invalid App Store URL for {slug}: {store}")
    smart_banner=(
        '<meta name="apple-itunes-app" '
        f'content="app-id={app_id_match.group(1)}">'
    )
    name=((app.get("name_i18n",{}) or {}).get(lang) or app["name"]).strip()
    tagline=(app.get("sub_i18n",{}) or {}).get(lang) or app.get("title","")
    cat=CAT_MAP.get(app.get("category",""),"Utilities")
    title=f"{name} — {tagline} | iOS App"[:60]
    pills="".join(f'<span class="pill">{esc(b)}</span>' for b in app.get("cta_bullets",[])[:4])
    blocks="".join(f'<div class="blk"><h3>{esc(s["h"])}</h3><p>{esc(s["p"])}</p></div>' for s in content.get("sections",[]))
    features="".join(f'<div>{esc(f)}</div>' for f in content.get("features",[])[:6])
    faqs="".join(f'<dt>{esc(q["q"])}</dt><dd>{esc(q["a"])}</dd>' for q in content.get("faqs",[]))
    shot=""
    shot_file=SHOTS.get(slug, gslug)
    if os.path.exists(os.path.join(SITE,"assets","shots",shot_file+".jpg")):
        shot=f'<img class="shot" src="/assets/shots/{shot_file}.jpg" alt="{esc(name)} screenshot" loading="lazy">'
    hreflang="".join(f'<link rel="alternate" hreflang="{HREFLANG[lg]}" href="{BASE}/app/{gslug}/{"" if lg=="en" else lg+"/"}">' for lg in LANG_ORDER)
    hreflang+=f'<link rel="alternate" hreflang="x-default" href="{BASE}/app/{gslug}/">'
    schema={
     "@context":"https://schema.org","@type":"SoftwareApplication","name":name,
     "operatingSystem":"iOS","applicationCategory":f"{cat}Application" if not cat.endswith("Application") else cat,
     "description":content.get("meta",""),"url":url,"image":icon_abs,
     "offers":{"@type":"Offer","price":"0","priceCurrency":"USD","description":"Free to download, one-time in-app unlock"},
     "publisher":{"@type":"Organization","name":"Lumi Studio","url":BASE+"/"},
     "installUrl":store,"downloadUrl":store,
    }
    faq_schema={"@context":"https://schema.org","@type":"FAQPage","mainEntity":[
        {"@type":"Question","name":q["q"],"acceptedAnswer":{"@type":"Answer","text":q["a"]}} for q in content.get("faqs",[])]}
    schema_str=json.dumps([schema,faq_schema],ensure_ascii=False,indent=0)
    html=PAGE.format(title=esc(title),meta=esc(content.get("meta","")),url=url,ogtitle=esc(name+" — "+tagline),
        icon=icon,icon_abs=icon_abs,schema=schema_str,smart_banner=smart_banner,
        generation_marker=content.get("generation_marker",""),
        kicker=esc(app.get("kicker","APP")),name=esc(name),
        hero_line=esc(content.get("hero_line",tagline)),store=store,pills=pills,shot=shot,
        intro=esc(content.get("intro","")),blocks=blocks,features=features,faqs=faqs,
        htmllang=L["html"],hreflang=hreflang,c_cta=esc(L["cta"]),c_get=esc(L["get"].format(name=name)),
        c_why=esc(L["why"].format(name=name)),
        c_features=esc(content.get("features_heading",L["features"])),
        c_faq=esc(L["faq"]),
        c_made=esc(L["made"]),c_all=esc(L["all"]))
    out_dir=os.path.join(SITE,"app",gslug) if lang=="en" else os.path.join(SITE,"app",gslug,lang)
    os.makedirs(out_dir,exist_ok=True)
    open(os.path.join(out_dir,"index.html"),"w",encoding="utf-8").write(html)
    return f"app/{gslug}/{suffix}index.html"


def _sitemap_lastmod(path, previous, today, runner=subprocess.run):
    relative=os.path.relpath(path,SITE)
    status=runner(
        ["git","status","--porcelain","--",relative],
        cwd=SITE,capture_output=True,text=True,check=False,
    )
    if status.returncode == 0 and status.stdout.strip():
        return today
    history=runner(
        ["git","log","-1","--format=%cs","--",relative],
        cwd=SITE,capture_output=True,text=True,check=False,
    )
    candidate=history.stdout.strip() if history.returncode == 0 else ""
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}",candidate):
        return candidate
    return previous or today


def rebuild_sitemap(apps):
    sitemap_path=os.path.join(SITE,"sitemap.xml")
    previous={}
    if os.path.exists(sitemap_path):
        old=open(sitemap_path,encoding="utf-8").read()
        previous=dict(re.findall(
            r"<url><loc>([^<]+)</loc><lastmod>(\d{4}-\d{2}-\d{2})</lastmod></url>",
            old,
        ))
    entries=[
        (f"{BASE}/",os.path.join(SITE,"index.html")),
        (f"{BASE}/.well-known/ai-catalog.json",os.path.join(SITE,".well-known","ai-catalog.json")),
        (f"{BASE}/.well-known/lumi-app-finder.mcp.json",os.path.join(SITE,".well-known","lumi-app-finder.mcp.json")),
        (f"{BASE}/.well-known/api-catalog",os.path.join(SITE,".well-known","api-catalog")),
        (f"{BASE}/.well-known/resourcesync",os.path.join(SITE,".well-known","resourcesync")),
    ]
    for s in ["unblur-image","scan-document","enhance-photo","clean-up-photo"]:
        entries.append((
            f"{BASE}/tools/{s}/",
            os.path.join(SITE,"tools",s,"index.html"),
        ))
    for slug in apps:
        if not apps[slug].get("url"): continue
        gslug=ICON.get(slug,slug)
        for lang in LANG_ORDER:
            d=os.path.join(SITE,"app",gslug,"index.html") if lang=="en" else os.path.join(SITE,"app",gslug,lang,"index.html")
            if os.path.exists(d):
                url=f"{BASE}/app/{gslug}/" if lang=="en" else f"{BASE}/app/{gslug}/{lang}/"
                entries.append((url,d))
    today=time.strftime("%Y-%m-%d")
    body='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for url,path in entries:
        lastmod=_sitemap_lastmod(path,previous.get(url),today)
        body+=f"  <url><loc>{url}</loc><lastmod>{lastmod}</lastmod></url>\n"
    body+="</urlset>\n"
    with open(sitemap_path,"w",encoding="utf-8") as handle:
        handle.write(body)
    return len(entries)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slug"); ap.add_argument("--all",action="store_true")
    ap.add_argument("--force",action="store_true"); ap.add_argument("--sitemap",action="store_true")
    ap.add_argument("--limit",type=int,default=99)
    ap.add_argument("--langs",default="en",help="逗號分隔語言(en,zh,ja,ko)或 all")
    a=ap.parse_args()
    apps=load_apps()

    if a.sitemap:
        n=rebuild_sitemap(apps); print(f"sitemap: {n} urls"); return

    langs=LANG_ORDER if a.langs=="all" else [x.strip() for x in a.langs.split(",") if x.strip() in LANGS]
    targets=[a.slug] if a.slug else (list(apps) if a.all else [])
    done=0
    for slug in targets:
        if done>=a.limit: break
        app=apps.get(slug)
        if not app or not app.get("url"):
            print(f"skip {slug}: 無資料/無連結"); continue
        gslug=ICON.get(slug,slug)
        for lang in langs:
            path=os.path.join(SITE,"app",gslug,"index.html") if lang=="en" else os.path.join(SITE,"app",gslug,lang,"index.html")
            if os.path.exists(path) and not a.force:
                print(f"= {slug}/{lang}: 已存在(跳過)"); continue
            print(f"→ {slug}/{lang}: 生成內容…")
            c=gen_content(app,lang)
            if not c: print(f"  ✗ {slug}/{lang} 生成失敗"); continue
            rel=build_page(slug,app,c,lang); print(f"  ✓ {rel}"); time.sleep(1)
        done+=1
    n=rebuild_sitemap(apps); print(f"\nsitemap 重建: {n} urls")


if __name__=="__main__":
    main()
