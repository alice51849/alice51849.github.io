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
"""
import os, sys, json, re, argparse, urllib.request, urllib.error, time

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

CAT_MAP = {"productivity":"Productivity","finance":"Finance","photo-utility":"Photography & Video",
 "health":"Health & Fitness","lifestyle":"Lifestyle","kids":"Education","education":"Education"}


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
CRITICAL: Never claim whether the app needs internet or works offline — you don't know, so don't state it. Don't invent specific numbers, ratings, or technical specs not provided. For privacy/data questions, say it's privacy-first and never sells your data. For pricing, it's a one-time purchase with no subscription."""

def gen_content(app):
    u=(f"App: {app['name']}\nTagline: {app.get('title','')} — {app.get('sub','')}\n"
       f"Category: {app.get('category','')}\nKeywords: {', '.join(app.get('keywords',[]))}\n"
       f"Selling points: {', '.join(app.get('cta_bullets',[]))}\nMonetization: one-time purchase (pay once), no subscription, privacy-first, no ads.\nWrite the landing page content as JSON now.")
    return _openai_json([{"role":"system","content":SYS},{"role":"user","content":u}])


def esc(s): return (str(s).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;"))

PAGE="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{title}</title>
<meta name="description" content="{meta}">
<link rel="canonical" href="{url}">
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
<div class="wrap">
<header class="nav"><a class="brand" href="/">✦ Lumi Studio</a></header>
<div class="hero">
<img class="app-icon" src="{icon}" alt="{name} app icon" width="104" height="104">
<div class="kicker">{kicker}</div>
<h1>{name}</h1>
<p class="sub">{hero_line}</p>
<a class="cta" href="{store}" rel="noopener">Download on the App Store →</a>
<div class="pills">{pills}</div>
{shot}
</div>
<section>
<p class="intro">{intro}</p>
</section>
<section>
<h2>Why {name}</h2>
{blocks}
</section>
<section>
<h2>Features</h2>
<div class="feat">{features}</div>
</section>
<section class="faq">
<h2>Frequently asked questions</h2>
<dl>{faqs}</dl>
</section>
<div style="text-align:center;padding:8px 0 30px">
<a class="cta" href="{store}" rel="noopener">Get {name} on the App Store →</a>
</div>
</div>
<div class="foot">
<div>Made by Lumi Studio — pay once, no ads, privacy-first.</div>
<div style="margin-top:8px"><a href="/">All apps</a> · <a href="{store}" rel="noopener">App Store</a></div>
</div>
</body>
</html>
"""

def build_page(slug, app, content):
    gslug=ICON.get(slug,slug)
    icon=f"/assets/icons/{gslug}.png"; icon_abs=BASE+icon
    url=f"{BASE}/app/{gslug}/"
    store=app.get("url","")
    name=app["name"]
    cat=CAT_MAP.get(app.get("category",""),"Utilities")
    title=f"{name} — {app.get('title','')} | iOS App"[:60]
    pills="".join(f'<span class="pill">{esc(b)}</span>' for b in app.get("cta_bullets",[])[:4])
    blocks="".join(f'<div class="blk"><h3>{esc(s["h"])}</h3><p>{esc(s["p"])}</p></div>' for s in content.get("sections",[]))
    features="".join(f'<div>{esc(f)}</div>' for f in content.get("features",[])[:6])
    faqs="".join(f'<dt>{esc(q["q"])}</dt><dd>{esc(q["a"])}</dd>' for q in content.get("faqs",[]))
    shot=""
    if slug in SHOTS:
        shot=f'<img class="shot" src="/assets/shots/{SHOTS[slug]}.jpg" alt="{esc(name)} screenshot" loading="lazy">'
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
    html=PAGE.format(title=esc(title),meta=esc(content.get("meta","")),url=url,ogtitle=esc(name+" — "+app.get("title","")),
        icon=icon,icon_abs=icon_abs,schema=schema_str,kicker=esc(app.get("kicker","APP")),name=esc(name),
        hero_line=esc(content.get("hero_line",app.get("sub",""))),store=store,pills=pills,shot=shot,
        intro=esc(content.get("intro","")),blocks=blocks,features=features,faqs=faqs)
    out_dir=os.path.join(SITE,"app",gslug)
    os.makedirs(out_dir,exist_ok=True)
    open(os.path.join(out_dir,"index.html"),"w",encoding="utf-8").write(html)
    return f"app/{gslug}/index.html"


def rebuild_sitemap(apps):
    urls=[f"{BASE}/"]
    for s in ["unblur-image","scan-document","enhance-photo","clean-up-photo"]:
        urls.append(f"{BASE}/tools/{s}/")
    for slug in apps:
        if not apps[slug].get("url"): continue
        gslug=ICON.get(slug,slug)
        if os.path.exists(os.path.join(SITE,"app",gslug,"index.html")):
            urls.append(f"{BASE}/app/{gslug}/")
    today=time.strftime("%Y-%m-%d")
    body='<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    for u in urls:
        body+=f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n"
    body+="</urlset>\n"
    open(os.path.join(SITE,"sitemap.xml"),"w").write(body)
    return len(urls)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--slug"); ap.add_argument("--all",action="store_true")
    ap.add_argument("--force",action="store_true"); ap.add_argument("--sitemap",action="store_true")
    ap.add_argument("--limit",type=int,default=99)
    a=ap.parse_args()
    apps=json.load(open(APPS_JSON,encoding="utf-8"))

    if a.sitemap:
        n=rebuild_sitemap(apps); print(f"sitemap: {n} urls"); return

    targets=[a.slug] if a.slug else (list(apps) if a.all else [])
    done=0
    for slug in targets:
        if done>=a.limit: break
        app=apps.get(slug)
        if not app or not app.get("url"):
            print(f"skip {slug}: 無資料/無連結"); continue
        gslug=ICON.get(slug,slug)
        path=os.path.join(SITE,"app",gslug,"index.html")
        if os.path.exists(path) and not a.force:
            print(f"= {slug}: 已存在(跳過)"); continue
        print(f"→ {slug}: 生成內容…")
        c=gen_content(app)
        if not c: print(f"  ✗ {slug} 內容生成失敗"); continue
        rel=build_page(slug,app,c); print(f"  ✓ {rel}")
        done+=1; time.sleep(1)
    n=rebuild_sitemap(apps); print(f"\nsitemap 重建: {n} urls")


if __name__=="__main__":
    main()
