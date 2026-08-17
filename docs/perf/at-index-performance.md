# Desempenho do autocomplete `@` — benchmark do índice de arquivos

Mede o impacto da mudança do autocomplete `@` em repositórios grandes
(> 20k arquivos). Antes, cada tecla `@` podia re-varrer o disco inteiro;
depois, a tecla ranqueia só da memória e a varredura corre em background.

Resultado principal: a latência por tecla cai de **~1,6 s** (re-scan +
rank) para **40–80 ms** (rank em memória) num repo sintético de **50 000
arquivos** — ~20–40× mais rápido, sem travar a TUI.

## Contexto

Bug relatado: em repos grandes, o `@` não listava arquivos (dropdown vazio
ou que sumia). Causa raiz:

1. `FileIndex.search_async` re-scaneava o disco se o último scan tinha
   mais de 0,3 s (`ensure_fresh`). Num repo grande o walk leva segundos,
   então **quase toda tecla** disparava uma varredura completa antes de
   ranquear — e o worker `exclusive=True` cancelava/re-enfileirava a cada
   tecla.
2. O índice era truncado em 20 000 arquivos (`INDEX_FILE_CAP`) em ordem
   arbitrária — o arquivo desejado podia nem entrar.
3. `rank_paths` rodava `fuzz.WRatio` sobre **todos** os paths por tecla,
   sem gate barato, sem priorizar basename e sem fallback para typos.

Mudança medida nesta branch (`perf/at-autocomplete`):

- `search_async` nunca mais re-scana por tecla: garante um scan inicial
  com single-flight (`_scan_gate`) e ranqueia da memória.
- Worker periódico `PromptBar.refresh_index` chama `refresh_if_stale`
  (default 5 s) — arquivo criado no disco aparece no `@` em até ~6 s,
  sem travar tecla.
- `rank_paths` ganhou gate de substring por token (query com `/` vira
  tokens de segmento), score com bônus de basename e fallback WRatio só
  quando o gate não acha nada (typo). O score roda em `process.extract`
  (C++), não em loop Python.
- Teto do índice vira config `file_index_cap` (default 50 000) e o
  intervalo do refresh vira `file_index_refresh_seconds` (default 5 s).

## Metodologia

- **Script**: `scripts/bench_at_index.py` (gera o repo, mede, imprime JSON).
- **Repo sintético determinístico**: 50 000 arquivos — `src/{app,web,api,
  core,lib}/mod_XXXX.py`, `src/deep/a/b/c/d/e/f/deep_file_XXXXX.rs`, mais
  `app.py`, `main.py`, `README.md` na raiz.
- **Máquina**: macOS (darwin), Python 3.14.0, rapidfuzz via `uv`.
- **Medição**: `_sample_ms` — aquece, calibra o lote para ~50 ms/round,
  pausa o GC e julga pela **mediana** (imune a GC e relógio); mesmo
  método de `tests/test_perf.py`.
- **Comparação**: `_rank_paths_old` embutido = implementação anterior
  (WRatio puro sobre tudo, corte 40), verificada contra o git.
- **Queries** (cada uma exercita um caminho):
  - `""` — vazio (lista inicial).
  - `ap` — substring comum (gate passa ~20k paths: `src/app/*` e `src/api/*`).
  - `app/main` — query com `/` (score por segmento).
  - `mod_0123` — id único (gate estreita para 5 arquivos).
  - `apl.py` — typo (gate vazio → fallback WRatio sobre tudo).
  - `a` — 1 caractere (gate passa quase tudo; pior caso do gate).

## Resultados

### `rank_paths` — novo vs antigo (mediana, ms, 50k paths)

| Query | Antigo (ms) | Novo (ms) | Δ |
|---|---|---|---|
| `""` | 0,0055 | 0,0055 | = |
| `ap` | 65,61 | 40,54 | **1,6× mais rápido** |
| `app/main` | 61,16 | 36,77 | **1,7× mais rápido** |
| `mod_0123` | 53,81 | 28,52 | **1,9× mais rápido** |
| `apl.py` (typo) | 55,70 | 67,78 | ~22% mais lento (fallback) |
| `a` | 64,64 | 37,45 | **1,7× mais rápido** |

Notas:

- Nas queries comuns (substring, path com `/`, id), o gate de substring
  estreita o conjunto e o score roda em C++ — daí a melhora.
- O typo é o único caso mais lento: o fallback varre o conjunto inteiro
  com WRatio (mesma operação do antigo) e ainda reordena por bônus com
  um teto interno maior (`limit × 4`). O custo é limitado e raro.
- Comparações confiáveis são **dentro da mesma execução** (old vs new):
  valores absolutos variam entre execuções conforme a carga da máquina.

### `search_async` com índice quente — custo por tecla na TUI (ms)

| Query | Mediana (ms) |
|---|---|
| `""` | 0,18 |
| `ap` | 53,4 |
| `app/main` | 51,4 |
| `mod_0123` | 41,2 |
| `apl.py` (typo) | 79,5 |
| `a` | 52,1 |

Antes, a tecla com índice velho custava **scan (1,56 s) + rank (~65 ms)**
— mais de 1,6 s travando o dropdown. Agora a tecla custa só o rank
(40–80 ms) e o scan roda em background.

### Varredura, memória e refresh periódico

| Métrica | Valor |
|---|---|
| `FileIndex.scan()` em 50k arquivos (walk + sort) | 1 562 ms |
| Memória pico do índice (tracemalloc, 50k paths) | 7,16 MB |
| `refresh_if_stale` — skip com índice fresco | 0,12 µs/chamada |
| `refresh_if_stale` — re-scan com índice velho (a cada ~5 s) | 411 ms |

O skip do worker periódico é desprezível (0,12 µs por tick). O re-scan de
411 ms a cada 5 s roda em `asyncio.to_thread` — o loop da TUI nunca
espera. A memória (7,16 MB para 50k) fica bem abaixo do teto do app.

### Achado intermediário (v1) e correção

A primeira execução (JSON `at_index_bench_v1.json`) mostrou o novo
`rank_paths` **mais lento** que o antigo em `ap` (86 ms) e `a` (84 ms):
o score era calculado chamando `fuzz.WRatio` em **loop Python** por
candidato. Corrigido delegando o score ao `process.extract` (C++) sobre o
conjunto já filtrado pelo gate — as queries passaram de 86→40 ms (`ap`) e
84→37 ms (`a`) sem mudar nenhum teste de comportamento. A v1 também tinha
uma medição contaminada do `refresh_if_stale` (a primeira chamada
re-scaneava); corrigida zerando o relógio do índice antes do loop.

## Como reproduzir

```bash
uv run python scripts/bench_at_index.py 50000          # imprime JSON no stdout
uv run python scripts/bench_at_index.py 50000 --keep   # mantém o repo sintético
uv run pytest tests/test_files.py tests/test_ui.py -q  # comportamento (fuzzy + @)
uv run pytest tests/test_perf.py -s                    # orçamento index_search (5 ms)
```

## Artefatos

- `scripts/bench_at_index.py` — benchmark (novo vs antigo, scan, memória, refresh).
- `docs/perf/results/at_index_bench.json` — números finais (v2).
- `docs/perf/results/at_index_bench_v1.json` — primeira execução (pré-correção do loop Python).
