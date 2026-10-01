🇺🇸 [English](https://albertosca.github.io/moonlighter/guides/finding-companies/) · 🇧🇷 [Português](finding-companies.md)

# Encontrar empresas

O moonlighter varre as empresas que você lista no `company_list.yaml`; ele não as encontra por você. Esta página é uma receita para achar candidatas à mão, usando o índice público de URLs do Common Crawl, e conferir cada uma antes de ela entrar na sua lista.

## O que funciona e o que não funciona

Um estudo de 25/09/2026 testou três métodos públicos. Só o índice do Common Crawl devolveu muitos slugs reais de empresas com pouco custo: uma ou duas requisições trouxeram cerca de 1.500 candidatas cada para Ashby e Workable, e de 8 a 10 em cada 10 amostradas eram portais vivos. Os buscadores responderam a consultas `site:` automatizadas com um captcha já na primeira requisição, e nenhum ATS publica um diretório dos seus clientes.

O índice tem semanas de atraso, então cerca de 2 em cada 10 candidatas são portais que já não existem, e ele não tem entradas úteis para o Lever. Recruitee e SmartRecruiters não foram testados.

## 1. Escolha a coleta mais recente

```sh
CRAWL=$(curl -s https://index.commoncrawl.org/collinfo.json | python3 -c "import json,sys; print(json.load(sys.stdin)[0]['id'])")
echo "$CRAWL"   # por exemplo CC-MAIN-2026-39
```

## 2. Liste os slugs candidatos

No Ashby, no Greenhouse e no Workable o slug da empresa é o primeiro trecho do caminho da URL do portal:

| ATS | Padrão de URL a consultar |
|---|---|
| Ashby | `jobs.ashbyhq.com/*` |
| Greenhouse | `job-boards.greenhouse.io/*` e `boards.greenhouse.io/*` |
| Workable | `apply.workable.com/*` (descarte o slug `j`, que faz parte das URLs de vaga) |

```sh
curl -s "https://index.commoncrawl.org/$CRAWL-index?url=jobs.ashbyhq.com/*&output=json&fl=url&limit=5000" \
  | python3 -c "import json,sys,urllib.parse; print('\n'.join(sorted({urllib.parse.unquote(json.loads(line)['url'].split('/')[3]).lower() for line in sys.stdin if line.strip()})))" \
  > ashby-candidates.txt
```

No InHire o slug é o subdomínio (`<slug>.inhire.app`): consulte `url=*.inhire.app` e pegue o primeiro rótulo do host em vez do caminho.

Vá com calma com o índice: a página dele pede que ninguém o sobrecarregue. Uma requisição por ATS, rodada à mão, é o uso esperado; uma resposta pode vir cortada no meio da lista, então rode de novo se a lista parecer curta.

## 3. Fique só com as empresas que você quer

Alguns milhares de portais não dizem quais empresas valem o seu tempo, e cada empresa na sua lista custa chamadas de LLM a cada scan. Filtre o arquivo até ficar com nomes que você reconhece ou que te interessam antes de conferir.

## 4. Confira se cada candidata é um portal vivo

Pergunte à listagem pública do próprio ATS, a mesma que o scanner do moonlighter usa. `200` é um portal vivo (pode estar sem vagas hoje); `404` é um portal que não existe mais:

| ATS | Conferência |
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

## 5. Coloque na sua lista

Ponha cada slug vivo sob o seu ATS no `company_list.yaml` (veja [Primeiro scan](../getting-started/first-scan.md)). O próximo `scan_and_evaluate` já os pega; para olhar uma empresa na hora sem editar a lista, peça o `scan_company` ou rode `moonlighter-scan --company ashby SLUG`.
