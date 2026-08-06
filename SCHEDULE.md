# 定時実行を外部から叩く

GitHub Actions の `schedule` はベストエフォートで、**実測で最大3時間半ずれた**。

```
us-close  予定 04:15 → 実際 05:41 （ 86分遅れ）
report    予定 06:00 → 実際 07:10 （ 70分遅れ）
jp-open   予定 09:15 → 実際 12:45 （210分遅れ）
```

寄り付き後セッションが昼過ぎに、引け前セッションが引け後に走ると、
プロンプトが想定する市場の状態と実際が食い違ったまま判断することになる。

外部の定時実行サービスから `repository_dispatch` を叩けば、この遅延は無くなる。
**受け口は実装・検証済み**（送信から数秒で起動することを確認）。
あとは叩く側を用意するだけ。

---

## 1. トークンを作る

GitHub の [Fine-grained personal access token](https://github.com/settings/personal-access-tokens/new) を作る。

| 項目 | 設定 |
|---|---|
| Repository access | **Only select repositories** → `kabusim` だけ |
| Permissions | **Contents: Read and write** のみ |
| Expiration | 1年（期限を控えておくこと） |

**他の権限は付けないこと。** これだけで `dispatches` を叩ける。
万一漏れても、影響はこのリポジトリの書き込みに限定される。

## 2. 叩く内容

エンドポイントは共通で、`event_type` と `client_payload` だけ変える。

```
POST https://api.github.com/repos/katsudon1cho/kabusim/dispatches

ヘッダ:
  Accept: application/vnd.github+json
  Authorization: Bearer <トークン>
  X-GitHub-Api-Version: 2022-11-28
  Content-Type: application/json
```

判断セッション:

```json
{"event_type":"session","client_payload":{"session":"jp-open"}}
```

価格更新:

```json
{"event_type":"prices"}
```

`session` に入れられるのは `jp-open` / `jp-close` / `us-open` / `us-close` / `report`。

動作確認用（トークンを自分の値に置き換える）:

```bash
curl -X POST https://api.github.com/repos/katsudon1cho/kabusim/dispatches \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer <トークン>" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  -d '{"event_type":"prices"}'
```

HTTP 204 が返れば成功（本文は空）。Actions タブに `repository_dispatch` の実行が現れる。

## 3. 登録する時刻

**サービス側のタイムゾーンを Asia/Tokyo にできるなら JST 列を、
できないなら UTC 列を使う。** 平日のみ。

| セッション | JST | UTC | 曜日(UTC) |
|---|---|---|---|
| jp-open | 09:05 | 00:05 | 月〜金 |
| jp-close | 14:40 | 05:40 | 月〜金 |
| us-open | 22:45 | 13:45 | 月〜金 |
| us-close | 04:15 | 19:15 | 月〜金 |
| report | 06:00 | 21:00 | 月〜金 |

`us-close` と `report` は JST では火〜土だが、**UTC では月〜金**になる。

価格更新は市場が開いている間だけ、20分間隔:

| 対象 | JST | UTC |
|---|---|---|
| 日本市場 | 09:00〜15:40 の20分ごと | 00:00〜06:40 |
| 米国市場 | 22:40〜05:40 の20分ごと | 13:40〜20:40 |

**米国は夏時間で1時間ずれる。** 11月に `us-*` と米国市場の価格更新を1時間後ろへ。

## 4. サービスの選択肢

**cron-job.org**（手軽）
無料。ブラウザのフォームだけで設定でき、デプロイ作業が要らない。
POSTボディとヘッダを指定できる。トークンは同サービスに保存される。

**Cloudflare Workers の Cron Triggers**（堅い）
無料枠で足りる。トークンを Worker のシークレットに置けるので、
第三者のフォームに貼らずに済む。実行時刻の精度も高い。
ただし Worker を1つデプロイする手間がかかる。

どちらでも構わない。**金銭が動かない実験なので、手軽さを取って問題ない。**

## 5. 切り替え後

GitHub 側の `schedule` は**残しておく**。外部サービスが止まったときの保険になる。
同じセッションが二重に走っても、`state.json` の更新は直列化されており
（`concurrency: kabusim-ledger`）、クールダウンと1日4件の上限が効くので
台帳が壊れることはない。

うまく動いているかは `usage_log.csv` の `ts` 列で分かる。
予定時刻とのずれが数分以内に収まっていれば成功。
