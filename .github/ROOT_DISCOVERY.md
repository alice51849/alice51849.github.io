# Root discovery 單一來源

正式 root repo 是 `alice51849/alice51849.github.io`；GitHub Pages 使用
legacy `main:/`，`open.cait518.cc` 是 canonical public host。Root 設定由
`scripts/public_site.py` 管理，Guide/Growth main 不在這個 repo 的發布範圍。

- `scripts/gen_root_discovery.py` 正常產生 `/.well-known/resourcesync`，三個
  URL 均由 `PUBLIC_SITE` 推導；其 SHA-256 為
  `0aa42115aff3eaf4908f2117ad0a0705ba9f33faa57c23367b1657f6f3f9df80`，
  與已查證的 Guide Source Description／paired feature root export 相同。
- 同一 generator 只更新 `llms.txt` 的 actual owned URL authority；不是全站
  字串替換，也不修改 support/App 頁或 Bridgy/Bsky profile identifiers。
  Profile URL 的 host 是 `bsky.app`／`web.brid.gy`，路徑中的歷史帳號字串
  不可被誤當成 canonical origin URL，更不能因修 discovery 擅自改社群身分。
- `.github/scripts/sync_standard_site.py` 僅 GET 公開 ATProto records，要求
  真實 publication 已宣告 `https://open.cait518.cc/ios-app-guide`。Canonical
  publication 已存在；先前同步失敗是舊 consumer 還在尋找 origin URL。
  不接受 origin alias、不修改 ATProto 紀錄、不捏造 canonical publication。
- 契約正常重生可能反映上游已完成的資料修正；2026-09-12 的 source readback
  保留全部 42 個 document AT-URI，並據實更新其 `generated_at` 與一筆既有
  `lumimathpro` tag。這不是 root owner 新發佈或變更任何 App／社群紀錄。

驗證需跑 `test_sync_standard_site.py`、`test_root_discovery.py`、
`test_gen_link_hub.py`，兩次正常產生須 bytes／mtime 穩定。正式發布後核對
Pages build commit、ResourceSync 三處 origin 歸零、llms public-host URL、
Standard.site 契約及 verifier body 的 exact GET；不能以 HTTP 200 取代 hash。
同時封存 331 份 Guide 歷史內容的 hash 與 Guide/Growth main SHA，避免跨 repo
修復夾帶未授權改動。這個流程不授權合併 paired Guide/Growth features。
