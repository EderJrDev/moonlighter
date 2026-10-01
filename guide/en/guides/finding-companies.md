🇺🇸 [English](finding-companies.md) · 🇧🇷 [Português](https://albertosca.github.io/moonlighter/pt/guides/finding-companies/)

# Finding companies

moonlighter scans the companies you list in `company_list.yaml`; it does not find them for you. This page is a recipe for finding candidates by hand, using the public Common Crawl URL index, and checking each one before it goes on your list.

## What works and what doesn't

A study on 2026-09-25 tried three public methods. Only the Common Crawl index gave many real company slugs cheaply: one or two requests yielded about 1,500 candidates each for Ashby and Workable, and 8 to 10 out of every 10 sampled were live boards. Search engines answered automated `site:` queries with a captcha on the first request, and no ATS publishes a directory of its customers.

The index is weeks old, so about 2 in 10 candidates are boards that no longer exist, and it has no usable entries for Lever. Recruitee and SmartRecruiters were not tried.

## 1. Pick the latest crawl

```sh
CRAWL=$(curl -s https://index.commoncrawl.org/collinfo.json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
echo "$CRAWL"   # e.g. CC-MAIN-2026-39
```

## 2. List candidate slugs

For Ashby, Greenhouse and Workable the company slug is the first path segment of the board URL:

| ATS | URL pattern to query |
|---|---|
| Ashby | `jobs.ashbyhq.com/*` |
| Greenhouse | `job-boards.greenhouse.io/*` and `boards.greenhouse.io/*` |
| Workable | `apply.workable.com/*` (drop the slug `j`, which is part of posting URLs) |

```sh
curl -s "https://index.commoncrawl.org/$CRAWL-index?url=jobs.ashbyhq.com/*&output=json&fl=url&limit=5000" \
  | python3 -c "import json,sys,urllib.parse; print('\n'.join(sorted({urllib.parse.unquote(json.loads(line)['url'].split('/')[3]).lower() for line in sys.stdin if line.strip()})))" \
  > ashby-candidates.txt
```

For InHire the slug is the subdomain (`<slug>.inhire.app`): query `url=*.inhire.app` and take the host's first label instead of the path.

Be gentle with the index: its homepage asks users not to overload it. One request per ATS, run by hand, is the intended use; a response can come back cut off mid-list, so run it again if the list looks short.

## 3. Keep only the companies you want

A few thousand boards say nothing about which companies are worth your time, and every company on your list costs LLM calls on each scan. Filter the file down to names you recognise or care about before checking them.

## 4. Check each candidate is a live board

Ask the ATS's own public listing, the same one moonlighter's scanner uses. A `200` is a live board (it may have no openings today); a `404` is gone:

| ATS | Check |
|---|---|
| Ashby | `curl -s -o /dev/null -w '%{http_code}' https://api.ashbyhq.com/posting-api/job-board/SLUG` |
| Greenhouse | `curl -s -o /dev/null -w '%{http_code}' https://boards-api.greenhouse.io/v1/boards/SLUG/jobs` |
| Workable | `curl -s -o /dev/null -w '%{http_code}' https://apply.workable.com/api/v1/widget/accounts/SLUG` |
| InHire | `curl -s -o /dev/null -w '%{http_code}' -H 'X-Tenant: SLUG' https://api.inhire.app/job-posts/public/pages` |
| Lever | `curl -s -o /dev/null -w '%{http_code}' 'https://api.lever.co/v0/postings/SLUG?mode=json&limit=1'` |

```sh
while read -r slug; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "https://api.ashbyhq.com/posting-api/job-board/$slug")
  [ "$code" = 200 ] && echo "$slug"
  sleep 1
done < ashby-candidates.txt
```

## 5. Add them to your list

Put each live slug under its ATS in `company_list.yaml` (see [First scan](../getting-started/first-scan.md)). The next `scan_and_evaluate` picks them up; to look at one company right away without editing the list, ask for `scan_company`, or run `moonlighter-scan --company ashby SLUG`.
